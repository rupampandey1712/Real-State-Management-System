using System.IdentityModel.Tokens.Jwt;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;
using StackExchange.Redis;

namespace Gateway.Infrastructure;

/// <summary>Revocation list shared with the Python services (keys written by the identity service).</summary>
public interface ITokenRevocationStore
{
    Task<bool> IsRevokedAsync(string? jti, string? subject, long issuedAt);
}

public sealed class RedisTokenRevocationStore(IConnectionMultiplexer redis) : ITokenRevocationStore
{
    public async Task<bool> IsRevokedAsync(string? jti, string? subject, long issuedAt)
    {
        var db = redis.GetDatabase();
        if (jti is not null && await db.KeyExistsAsync($"jwt:deny:{jti}")) return true;
        if (subject is null) return false;
        var before = await db.StringGetAsync($"jwt:revoked_before:{subject}");
        return before.HasValue && long.TryParse(before.ToString(), out var cutoff) && issuedAt < cutoff;
    }
}

public sealed class NoRevocationStore : ITokenRevocationStore
{
    public Task<bool> IsRevokedAsync(string? jti, string? subject, long issuedAt) => Task.FromResult(false);
}

public static class EdgeAuthenticationExtensions
{
    /// <summary>JWT bearer validation at the edge. Keys come from the identity service's JWKS
    /// (RS256, rotated by identity); the handler refreshes them automatically when a new kid appears.</summary>
    public static IServiceCollection AddEdgeAuthentication(this IServiceCollection services, IConfiguration config, IConnectionMultiplexer? redis)
    {
        if (redis is not null) services.AddSingleton<ITokenRevocationStore>(new RedisTokenRevocationStore(redis));
        else services.AddSingleton<ITokenRevocationStore, NoRevocationStore>();

        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer(o =>
        {
            o.MetadataAddress = config["Jwt:MetadataAddress"]!;
            o.RequireHttpsMetadata = config.GetValue("Jwt:RequireHttpsMetadata", true);
            o.MapInboundClaims = false;
            o.RefreshOnIssuerKeyNotFound = true;
            o.TokenValidationParameters = new TokenValidationParameters
            {
                ValidIssuer = config["Jwt:Issuer"],
                ValidAudience = config["Jwt:Audience"],
                ValidAlgorithms = [SecurityAlgorithms.RsaSha256],
                RoleClaimType = "role",
                NameClaimType = JwtRegisteredClaimNames.Sub,
                ClockSkew = TimeSpan.FromSeconds(30),
            };
            o.Events = new JwtBearerEvents
            {
                OnTokenValidated = async ctx =>
                {
                    var store = ctx.HttpContext.RequestServices.GetRequiredService<ITokenRevocationStore>();
                    var principal = ctx.Principal!;
                    long.TryParse(principal.FindFirst(JwtRegisteredClaimNames.Iat)?.Value, out var iat);
                    if (await store.IsRevokedAsync(principal.FindFirst(JwtRegisteredClaimNames.Jti)?.Value,
                            principal.FindFirst(JwtRegisteredClaimNames.Sub)?.Value, iat))
                        ctx.Fail("Token revoked.");
                },
                // Let EdgeTokenMiddleware / authorization write the envelope instead of an empty 401.
                OnChallenge = ctx =>
                {
                    ctx.HandleResponse();
                    return ErrorEnvelope.WriteAsync(ctx.HttpContext, StatusCodes.Status401Unauthorized, "unauthorized", "Sign in to continue.");
                },
            };
        });
        return services;
    }
}

/// <summary>A request that *sends* a bearer token must send a valid one, even on public routes — expired,
/// forged or revoked tokens are rejected at the edge. Auth endpoints are exempt so refresh can work.</summary>
public sealed class EdgeTokenMiddleware(RequestDelegate next)
{
    public Task InvokeAsync(HttpContext ctx)
    {
        var sentBearer = ctx.Request.Headers.Authorization.ToString().StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase);
        if (sentBearer && ctx.User.Identity?.IsAuthenticated != true && !ctx.Request.Path.StartsWithSegments("/api/v1/auth"))
            return ErrorEnvelope.WriteAsync(ctx, StatusCodes.Status401Unauthorized, "token_invalid", "Your session has expired. Sign in again.");
        return next(ctx);
    }
}
