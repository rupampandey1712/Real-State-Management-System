using System.Collections.Concurrent;
using System.Net;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Http.Resilience;
using Polly;
using Polly.CircuitBreaker;
using Polly.Retry;
using StackExchange.Redis;
using Yarp.ReverseProxy;
using Yarp.ReverseProxy.Forwarder;
using Yarp.ReverseProxy.Model;

namespace Gateway.Infrastructure;

/// <summary>
/// Wraps YARP's upstream handler with Polly:
///  • retry (2×, exponential + jitter) — only for GET/HEAD, which are safe to repeat;
///  • circuit breaker per upstream service — after sustained failures, calls fail fast for 15 s
///    (ForwarderErrorMiddleware turns that into a 503 envelope) instead of piling onto a sick service.
/// YARP's own active/passive health checks (appsettings.json) complement this at the destination level.
/// </summary>
public sealed class ResilientForwarderHttpClientFactory(ILogger<ResilientForwarderHttpClientFactory> logger) : ForwarderHttpClientFactory
{
    private static readonly HashSet<HttpStatusCode> Transient =
        [HttpStatusCode.BadGateway, HttpStatusCode.ServiceUnavailable, HttpStatusCode.GatewayTimeout];

    private readonly ConcurrentDictionary<string, ResiliencePipeline<HttpResponseMessage>> _safe = new();
    private readonly ConcurrentDictionary<string, ResiliencePipeline<HttpResponseMessage>> _unsafe = new();

    protected override HttpMessageHandler WrapHandler(ForwarderHttpClientContext context, HttpMessageHandler handler)
    {
        var inner = base.WrapHandler(context, handler);
        return new ResilienceHandler(PipelineFor) { InnerHandler = inner };
    }

    private ResiliencePipeline<HttpResponseMessage> PipelineFor(HttpRequestMessage request)
    {
        var upstream = request.RequestUri?.Authority ?? "unknown";
        var safe = request.Method == HttpMethod.Get || request.Method == HttpMethod.Head;
        return safe ? _safe.GetOrAdd(upstream, u => Build(u, retry: true)) : _unsafe.GetOrAdd(upstream, u => Build(u, retry: false));
    }

    private ResiliencePipeline<HttpResponseMessage> Build(string upstream, bool retry)
    {
        var shouldHandle = new PredicateBuilder<HttpResponseMessage>()
            .Handle<HttpRequestException>()
            .HandleResult(r => Transient.Contains(r.StatusCode));

        var builder = new ResiliencePipelineBuilder<HttpResponseMessage>();
        if (retry)
        {
            builder.AddRetry(new RetryStrategyOptions<HttpResponseMessage>
            {
                ShouldHandle = shouldHandle,
                MaxRetryAttempts = 2,
                BackoffType = DelayBackoffType.Exponential,
                UseJitter = true,
                Delay = TimeSpan.FromMilliseconds(200),
                OnRetry = args =>
                {
                    logger.LogWarning("Retrying {Upstream} (attempt {Attempt})", upstream, args.AttemptNumber + 1);
                    return ValueTask.CompletedTask;
                },
            });
        }
        builder.AddCircuitBreaker(new CircuitBreakerStrategyOptions<HttpResponseMessage>
        {
            ShouldHandle = shouldHandle,
            FailureRatio = 0.5,
            MinimumThroughput = 10,
            SamplingDuration = TimeSpan.FromSeconds(30),
            BreakDuration = TimeSpan.FromSeconds(15),
            OnOpened = _ =>
            {
                logger.LogError("Circuit opened for {Upstream}", upstream);
                return ValueTask.CompletedTask;
            },
            OnClosed = _ =>
            {
                logger.LogInformation("Circuit closed for {Upstream}", upstream);
                return ValueTask.CompletedTask;
            },
        });
        return builder.Build();
    }
}

public sealed class RedisHealthCheck(IConnectionMultiplexer? redis) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default)
    {
        if (redis is null) return HealthCheckResult.Healthy("Redis not configured (in-memory mode).");
        try
        {
            var latency = await redis.GetDatabase().PingAsync();
            return HealthCheckResult.Healthy($"ping {latency.TotalMilliseconds:F0} ms");
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy("Redis unreachable", ex);
        }
    }
}

/// <summary>/health/deep — YARP's view of every upstream destination (from active + passive health checks).</summary>
public static class UpstreamHealth
{
    public static IResult Report(IProxyStateLookup proxy)
    {
        var clusters = proxy.GetClusters().ToDictionary(
            c => c.ClusterId,
            c => c.Destinations.Values.Select(d => new
            {
                destination = d.DestinationId,
                address = d.Model.Config.Address,
                active = d.Health.Active.ToString(),
                passive = d.Health.Passive.ToString(),
            }));
        var degraded = proxy.GetClusters().Any(c => c.Destinations.Values.Any(d =>
            d.Health.Active == DestinationHealth.Unhealthy || d.Health.Passive == DestinationHealth.Unhealthy));
        return Results.Ok(new { status = degraded ? "degraded" : "ok", clusters });
    }
}
