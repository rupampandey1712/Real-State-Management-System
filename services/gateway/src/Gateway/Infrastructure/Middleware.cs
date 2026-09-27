using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Authorization.Policy;
using Microsoft.AspNetCore.Diagnostics;
using Yarp.ReverseProxy.Forwarder;

namespace Gateway.Infrastructure;

/// <summary>Accepts or creates X-Request-Id, forwards it upstream, echoes it back, and adds it to the log scope.</summary>
public sealed class RequestIdMiddleware(RequestDelegate next, ILogger<RequestIdMiddleware> logger)
{
    private const string Header = "X-Request-Id";
    private const string ItemKey = "request-id";

    public static string Get(HttpContext ctx) => ctx.Items[ItemKey] as string ?? "";

    public async Task InvokeAsync(HttpContext ctx)
    {
        var incoming = ctx.Request.Headers[Header].ToString();
        var id = incoming.Length is > 0 and <= 64 && incoming.All(char.IsAsciiLetterOrDigit) ? incoming : Guid.NewGuid().ToString("N");
        ctx.Items[ItemKey] = id;
        ctx.Request.Headers[Header] = id; // YARP forwards request headers upstream
        ctx.Response.OnStarting(() =>
        {
            ctx.Response.Headers[Header] = id;
            return Task.CompletedTask;
        });
        using (logger.BeginScope(new Dictionary<string, object> { ["request_id"] = id }))
        {
            var started = System.Diagnostics.Stopwatch.GetTimestamp();
            try
            {
                await next(ctx);
            }
            finally
            {
                if (!ctx.Request.Path.StartsWithSegments("/health"))
                    logger.LogInformation("HTTP {Method} {Path} -> {Status} in {ElapsedMs} ms (route {Route})",
                        ctx.Request.Method, ctx.Request.Path.Value, ctx.Response.StatusCode,
                        Math.Round(System.Diagnostics.Stopwatch.GetElapsedTime(started).TotalMilliseconds, 1),
                        ctx.GetEndpoint()?.DisplayName ?? "-");
            }
        }
    }
}

/// <summary>Global exception handling: log once, return the envelope, never leak internals.</summary>
public sealed class GlobalExceptionHandler(ILogger<GlobalExceptionHandler> logger) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext ctx, Exception exception, CancellationToken ct)
    {
        switch (exception)
        {
            case StackExchange.Redis.RedisException:
                // Rate limiter / cache store unavailable: fail closed for the protected routes.
                logger.LogWarning(exception, "Redis unavailable");
                await ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status503ServiceUnavailable, "service_unavailable",
                    "This feature is temporarily unavailable. Try again shortly.", TimeSpan.FromSeconds(30));
                break;
            case BadHttpRequestException bad:
                await ErrorEnvelope.WriteAsync(ctx, bad.StatusCode, "bad_request", "The request couldn't be read.");
                break;
            default:
                logger.LogError(exception, "Unhandled gateway error");
                await ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status500InternalServerError, "internal", "Something went wrong.");
                break;
        }
        return true;
    }
}

/// <summary>Turns YARP proxy failures (service down, circuit open, timeout) into the standard envelope.</summary>
public sealed class ForwarderErrorMiddleware(RequestDelegate next, ILogger<ForwarderErrorMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext ctx)
    {
        await next(ctx);
        var error = ctx.GetForwarderErrorFeature();
        if (error is null) return;

        logger.LogWarning(error.Exception, "Upstream failure {Error} for {Path}", error.Error, ctx.Request.Path);
        if (error.Error is ForwarderError.RequestTimedOut)
            await ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status504GatewayTimeout, "upstream_timeout", "The service took too long to respond.");
        else if (error.Error is ForwarderError.RequestCanceled)
            return; // client went away
        else
            await ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status503ServiceUnavailable, "service_unavailable",
                "This part of EstateAI is temporarily unavailable. Try again shortly.", TimeSpan.FromSeconds(10));
    }
}

/// <summary>Writes 401/403 from authorization as envelopes instead of empty bodies.</summary>
public sealed class EnvelopeAuthorizationResultHandler : IAuthorizationMiddlewareResultHandler
{
    private readonly AuthorizationMiddlewareResultHandler _default = new();

    public Task HandleAsync(RequestDelegate next, HttpContext ctx, AuthorizationPolicy policy, PolicyAuthorizationResult result)
    {
        if (result.Challenged)
            return ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status401Unauthorized, "unauthorized", "Sign in to continue.");
        if (result.Forbidden)
            return ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status403Forbidden, "forbidden", "You don't have permission to do this.");
        return _default.HandleAsync(next, ctx, policy, result);
    }
}

public sealed class SecurityHeadersMiddleware(RequestDelegate next)
{
    public Task InvokeAsync(HttpContext ctx)
    {
        ctx.Response.OnStarting(() =>
        {
            var h = ctx.Response.Headers;
            h["X-Content-Type-Options"] = "nosniff";
            h["X-Frame-Options"] = "DENY";
            h["Referrer-Policy"] = "strict-origin-when-cross-origin";
            h.Remove("Server");
            return Task.CompletedTask;
        });
        return next(ctx);
    }
}
