using System.Text.Json;

namespace Gateway.Infrastructure;

/// <summary>The same error envelope every EstateAI service returns (docs/design.md §3.1).</summary>
public static class ErrorEnvelope
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public static Task WriteAsync(HttpContext ctx, int status, string code, string message, TimeSpan? retryAfter = null)
    {
        if (ctx.Response.HasStarted) return Task.CompletedTask;
        ctx.Response.Clear();
        ctx.Response.StatusCode = status;
        ctx.Response.ContentType = "application/json";
        if (retryAfter is { } wait) ctx.Response.Headers.RetryAfter = ((int)Math.Ceiling(wait.TotalSeconds)).ToString();
        var body = new
        {
            error = new { code, message, details = Array.Empty<object>(), request_id = RequestIdMiddleware.Get(ctx) }
        };
        return ctx.Response.WriteAsync(JsonSerializer.Serialize(body, Json));
    }
}
