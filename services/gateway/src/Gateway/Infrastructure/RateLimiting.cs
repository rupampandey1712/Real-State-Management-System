using System.Net;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.RateLimiting;
using RedisRateLimiting;
using StackExchange.Redis;

namespace Gateway.Infrastructure;

public sealed record RateRule(int PermitLimit, TimeSpan Window);

/// <summary>
/// Distributed sliding-window limits in Redis, partitioned per signed-in user (sub) or per client IP.
/// Named policies are attached to YARP routes (appsettings.json → RateLimiterPolicy). A broad
/// per-IP global limiter runs in memory so a Redis outage never takes the whole API down;
/// the named (AI, auth, enquiry) policies fail closed via GlobalExceptionHandler.
/// </summary>
public static class RateLimitingExtensions
{
    public static IServiceCollection AddGatewayRateLimiting(this IServiceCollection services, IConfiguration config, IConnectionMultiplexer? redis)
    {
        var rules = new Dictionary<string, RateRule>
        {
            ["nl_search"] = Rule(config, "NlSearch", 30, TimeSpan.FromMinutes(1)),
            ["qa"] = Rule(config, "Qa", 20, TimeSpan.FromMinutes(1)),
            ["describe"] = Rule(config, "Describe", 10, TimeSpan.FromMinutes(1)),
            ["enquiry"] = Rule(config, "Enquiry", 5, TimeSpan.FromHours(1)),
            ["auth"] = Rule(config, "Auth", 10, TimeSpan.FromMinutes(1)),
            ["events"] = Rule(config, "Events", 120, TimeSpan.FromMinutes(1)),
        };
        var global = Rule(config, "GlobalPerIp", 600, TimeSpan.FromMinutes(1));

        services.AddRateLimiter(o =>
        {
            o.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
            o.OnRejected = (ctx, _) =>
            {
                TimeSpan? wait = ctx.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retry) ? retry : TimeSpan.FromSeconds(30);
                return new ValueTask(ErrorEnvelope.WriteAsync(ctx.HttpContext, StatusCodes.Status429TooManyRequests,
                    "rate_limited", "Too many requests. Please wait a moment and try again.", wait));
            };

            o.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(ctx =>
                RateLimitPartition.GetSlidingWindowLimiter(ClientIp(ctx), _ => new SlidingWindowRateLimiterOptions
                {
                    PermitLimit = global.PermitLimit, Window = global.Window, SegmentsPerWindow = 6, QueueLimit = 0,
                }));

            foreach (var (name, rule) in rules)
            {
                o.AddPolicy(name, ctx =>
                {
                    var key = $"rl:{name}:{PartitionKey(ctx)}";
                    return redis is null
                        ? RateLimitPartition.GetSlidingWindowLimiter(key, _ => new SlidingWindowRateLimiterOptions
                        {
                            PermitLimit = rule.PermitLimit, Window = rule.Window, SegmentsPerWindow = 6, QueueLimit = 0,
                        })
                        : RedisRateLimitPartition.GetSlidingWindowRateLimiter(key, _ => new RedisSlidingWindowRateLimiterOptions
                        {
                            PermitLimit = rule.PermitLimit, Window = rule.Window, ConnectionMultiplexerFactory = () => redis,
                        });
                });
            }
        });
        return services;
    }

    private static RateRule Rule(IConfiguration config, string name, int limit, TimeSpan window) => new(
        config.GetValue($"RateLimits:{name}:PermitLimit", limit),
        TimeSpan.FromSeconds(config.GetValue($"RateLimits:{name}:WindowSeconds", (int)window.TotalSeconds)));

    private static string PartitionKey(HttpContext ctx) =>
        ctx.User.Identity?.IsAuthenticated == true && ctx.User.FindFirst("sub")?.Value is { } sub ? $"user:{sub}" : $"ip:{ClientIp(ctx)}";

    private static string ClientIp(HttpContext ctx) => ctx.Connection.RemoteIpAddress?.ToString() ?? IPAddress.None.ToString();
}
