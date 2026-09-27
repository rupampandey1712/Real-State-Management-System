using StackExchange.Redis;

namespace Gateway.Infrastructure;

/// <summary>
/// Edge output cache for anonymous GETs, stored in Redis so every gateway replica shares it.
/// Requests carrying Authorization or responses setting cookies are never cached (default policy).
/// TTLs are deliberately short: services also cache (two-level, event-invalidated), and the edge
/// cache only absorbs bursts. A listing change can therefore take up to 30 s to show at the edge.
/// </summary>
public static class CachingExtensions
{
    public static IServiceCollection AddGatewayOutputCache(this IServiceCollection services, IConnectionMultiplexer? redis)
    {
        services.AddOutputCache(o =>
        {
            o.AddPolicy("public-short", b => b.Expire(TimeSpan.FromSeconds(30)).SetVaryByQuery("*").Tag("listings"));
            o.AddPolicy("suggestions", b => b.Expire(TimeSpan.FromMinutes(5)).Tag("listings"));
            o.AddPolicy("media", b => b.Expire(TimeSpan.FromHours(6)));
        });
        if (redis is not null)
        {
            services.AddStackExchangeRedisOutputCache(o =>
            {
                o.InstanceName = "gw-oc:";
                o.ConnectionMultiplexerFactory = () => Task.FromResult(redis);
            });
        }
        return services;
    }
}
