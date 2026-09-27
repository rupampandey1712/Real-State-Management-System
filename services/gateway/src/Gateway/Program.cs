// EstateAI API gateway — YARP on ASP.NET Core (ADR-0014).
// Pipeline: request id → exception handler → security headers → CORS → authentication (JWT, RS256 via JWKS)
//           → edge token check → authorization → rate limiting (Redis) → output cache (Redis) → timeouts → YARP.
// Upstream calls get retries (GET only) + a circuit breaker per service (Polly), plus YARP active/passive health checks.

using Gateway.Infrastructure;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using StackExchange.Redis;
using Yarp.ReverseProxy.Forwarder;

var builder = WebApplication.CreateBuilder(args);
var config = builder.Configuration;

builder.Logging.ClearProviders();
builder.Logging.AddJsonConsole(o => o.IncludeScopes = true);
builder.WebHost.ConfigureKestrel(o =>
{
    o.AddServerHeader = false;
    o.Limits.MaxRequestBodySize = config.GetValue("Gateway:MaxRequestBodyBytes", 1_048_576L); // routes can raise it
});

// ── Redis (rate limits, output cache, token revocation). Empty connection string → in-memory fallbacks.
var redisConnection = config["Redis:ConnectionString"];
IConnectionMultiplexer? redis = null;
if (!string.IsNullOrWhiteSpace(redisConnection))
{
    var options = ConfigurationOptions.Parse(redisConnection);
    options.AbortOnConnectFail = false; // keep starting; health check reports it
    redis = ConnectionMultiplexer.Connect(options);
    builder.Services.AddSingleton(redis);
}

builder.Services.AddProblemDetails();
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p
    .WithOrigins(config.GetSection("Cors:Origins").Get<string[]>() ?? [])
    .AllowAnyHeader().AllowAnyMethod().AllowCredentials()
    .WithExposedHeaders("X-Request-Id", "Retry-After")));

builder.Services.AddEdgeAuthentication(config, redis);
builder.Services.AddSingleton<IAuthorizationMiddlewareResultHandler, EnvelopeAuthorizationResultHandler>();
builder.Services.AddAuthorizationBuilder()
    .AddPolicy("authenticated", p => p.RequireAuthenticatedUser())
    .AddPolicy("agent", p => p.RequireRole("agent", "admin"))
    .AddPolicy("admin", p => p.RequireRole("admin"));

builder.Services.AddGatewayRateLimiting(config, redis);
builder.Services.AddGatewayOutputCache(redis);
builder.Services.AddRequestTimeouts(o =>
{
    o.DefaultPolicy = new() { Timeout = TimeSpan.FromSeconds(30), TimeoutStatusCode = StatusCodes.Status504GatewayTimeout };
    o.AddPolicy("ai-stream", TimeSpan.FromSeconds(90));
    o.AddPolicy("upload", TimeSpan.FromSeconds(120));
});

builder.Services.AddHealthChecks().AddCheck("redis", new RedisHealthCheck(redis), tags: ["ready"]);

builder.Services.AddSingleton<IForwarderHttpClientFactory, ResilientForwarderHttpClientFactory>();
builder.Services.AddReverseProxy().LoadFromConfig(config.GetSection("ReverseProxy"));

builder.Services.AddOpenTelemetry()
    .ConfigureResource(r => r.AddService("gateway"))
    .WithTracing(t =>
    {
        // Health probes (ours and YARP's active checks every 10 s) would drown real traffic, so they're not traced.
        // The YARP activity source is left out for the same reason: its per-request spans are covered by the
        // ASP.NET Core server span and the HttpClient span to the upstream (which carries `traceparent`).
        t.AddAspNetCoreInstrumentation(o => o.Filter = ctx => !ctx.Request.Path.StartsWithSegments("/health"))
         .AddHttpClientInstrumentation(o => o.FilterHttpRequestMessage = r => r.RequestUri?.AbsolutePath.StartsWith("/health") != true);
        if (!string.IsNullOrWhiteSpace(config["OTEL_EXPORTER_OTLP_ENDPOINT"])) t.AddOtlpExporter();
    });

var app = builder.Build();

app.UseMiddleware<RequestIdMiddleware>();
app.UseExceptionHandler();
app.UseMiddleware<SecurityHeadersMiddleware>();
if (!app.Environment.IsDevelopment()) app.UseHsts();
app.UseCors();
app.UseAuthentication();
app.UseMiddleware<EdgeTokenMiddleware>();
app.UseAuthorization();
app.UseRateLimiter();
app.UseOutputCache();
app.UseRequestTimeouts();

app.MapGet("/health", () => Results.Ok(new { status = "ok", service = "gateway" }));
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = c => c.Tags.Contains("ready") });
app.MapGet("/health/deep", UpstreamHealth.Report);

app.MapReverseProxy(proxy =>
{
    proxy.UseMiddleware<ForwarderErrorMiddleware>();
    proxy.UseSessionAffinity();
    proxy.UseLoadBalancing();
    proxy.UsePassiveHealthChecks();
});

// Anything that isn't a mapped route (including /internal/*) gets the standard 404 envelope.
app.MapFallback(ctx => ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status404NotFound, "not_found", "Unknown route."));

app.Run();

public partial class Program;
