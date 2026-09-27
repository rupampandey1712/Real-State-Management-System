using System.Net;
using System.Net.Http.Headers;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text.Json;
using Gateway.Infrastructure;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Protocols;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;
using Microsoft.IdentityModel.Tokens;

namespace Gateway.Tests;

/// <summary>Runs the real gateway (in-memory Redis fallbacks) against a real Kestrel upstream.</summary>
public sealed class GatewayFixture : IAsyncLifetime
{
    public readonly RSA Rsa = RSA.Create(2048);
    public int SearchHits;
    public int FlakyCalls;
    private WebApplication? _upstream;
    public WebApplicationFactory<Program> Factory { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        var up = WebApplication.CreateBuilder();
        up.WebHost.UseUrls("http://127.0.0.1:0");
        _upstream = up.Build();
        _upstream.MapGet("/health/ready", () => Results.Ok());
        _upstream.MapGet("/api/v1/search", () => { Interlocked.Increment(ref SearchHits); return Results.Ok(new { items = Array.Empty<object>() }); });
        _upstream.MapGet("/api/v1/listings/{id}", (string id) =>
            id == "flaky" && Interlocked.Increment(ref FlakyCalls) == 1 ? Results.StatusCode(503) : Results.Ok(new { id }));
        _upstream.MapPost("/api/v1/search/nl", () => Results.Ok(new { items = Array.Empty<object>() }));
        _upstream.MapGet("/api/v1/agent/listings", () => Results.Ok(Array.Empty<object>()));
        await _upstream.StartAsync();
        var upstreamUrl = _upstream.Urls.First() + "/";

        Factory = new WebApplicationFactory<Program>().WithWebHostBuilder(b =>
        {
            b.UseSetting("Redis:ConnectionString", "");
            b.UseSetting("Jwt:RequireHttpsMetadata", "false");
            b.UseSetting("RateLimits:NlSearch:PermitLimit", "2");
            foreach (var cluster in new[] { "identity", "listing", "search", "ai" })
                b.UseSetting($"ReverseProxy:Clusters:{cluster}:Destinations:d1:Address", upstreamUrl);
            b.UseSetting("ReverseProxy:Clusters:engagement:Destinations:d1:Address", "http://127.0.0.1:1/"); // nothing listens
            b.UseSetting("ReverseProxy:Clusters:engagement:HealthCheck:Active:Enabled", "false");
            b.ConfigureTestServices(s =>
            {
                s.AddSingleton<ITokenRevocationStore>(new DenyJti("revoked-jti"));
                s.PostConfigure<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme, o =>
                {
                    var oidc = new OpenIdConnectConfiguration { Issuer = "estateai-identity" };
                    oidc.SigningKeys.Add(new RsaSecurityKey(Rsa) { KeyId = "test" });
                    // Replace the JWKS discovery (identity service) with a static key for tests.
                    o.ConfigurationManager = new StaticConfigurationManager<OpenIdConnectConfiguration>(oidc);
                });
            });
        });
    }

    public string Token(string role, string jti = "jti-1") => new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor
    {
        Issuer = "estateai-identity",
        Audience = "estateai",
        Subject = new ClaimsIdentity([new Claim("sub", "user-1"), new Claim("role", role), new Claim("jti", jti)]),
        Expires = DateTime.UtcNow.AddMinutes(5),
        SigningCredentials = new SigningCredentials(new RsaSecurityKey(Rsa) { KeyId = "test" }, SecurityAlgorithms.RsaSha256),
    });

    public async Task DisposeAsync()
    {
        await Factory.DisposeAsync();
        if (_upstream is not null) await _upstream.DisposeAsync();
    }

    private sealed class DenyJti(string jti) : ITokenRevocationStore
    {
        public Task<bool> IsRevokedAsync(string? tokenJti, string? subject, long issuedAt) => Task.FromResult(tokenJti == jti);
    }
}

public sealed class GatewayTests(GatewayFixture fx) : IClassFixture<GatewayFixture>
{
    private HttpClient Client(string? token = null)
    {
        var client = fx.Factory.CreateClient();
        if (token is not null) client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return client;
    }

    private static async Task<string> ErrorCode(HttpResponseMessage r) =>
        JsonDocument.Parse(await r.Content.ReadAsStringAsync()).RootElement.GetProperty("error").GetProperty("code").GetString()!;

    [Fact]
    public async Task Internal_routes_are_never_exposed()
    {
        var r = await Client().GetAsync("/internal/listings/abc/facts");
        Assert.Equal(HttpStatusCode.NotFound, r.StatusCode);
        Assert.Equal("not_found", await ErrorCode(r));
        Assert.True(r.Headers.Contains("X-Request-Id"));
    }

    [Fact]
    public async Task Anonymous_search_is_output_cached()
    {
        var before = fx.SearchHits;
        var c = Client();
        Assert.Equal(HttpStatusCode.OK, (await c.GetAsync("/api/v1/search?city=Pune&cache=1")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await c.GetAsync("/api/v1/search?city=Pune&cache=1")).StatusCode);
        Assert.Equal(before + 1, fx.SearchHits);
    }

    [Fact]
    public async Task Transient_upstream_failure_on_GET_is_retried()
    {
        var r = await Client().GetAsync("/api/v1/listings/flaky");
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        Assert.True(fx.FlakyCalls >= 2);
    }

    [Fact]
    public async Task Unreachable_service_returns_503_envelope()
    {
        var r = await Client().GetAsync("/api/v1/me/favourites", HttpCompletionOption.ResponseHeadersRead);
        Assert.Equal(HttpStatusCode.Unauthorized, r.StatusCode); // auth runs before proxying

        var r2 = await Client(fx.Token("buyer")).PostAsync("/api/v1/listings/abc/enquiries", new StringContent("{}"));
        Assert.Equal(HttpStatusCode.ServiceUnavailable, r2.StatusCode);
        Assert.Equal("service_unavailable", await ErrorCode(r2));
    }

    [Fact]
    public async Task Agent_routes_enforce_roles_at_the_edge()
    {
        Assert.Equal(HttpStatusCode.Unauthorized, (await Client().GetAsync("/api/v1/agent/listings")).StatusCode);
        var forbidden = await Client(fx.Token("buyer")).GetAsync("/api/v1/agent/listings");
        Assert.Equal(HttpStatusCode.Forbidden, forbidden.StatusCode);
        Assert.Equal("forbidden", await ErrorCode(forbidden));
        Assert.Equal(HttpStatusCode.OK, (await Client(fx.Token("agent")).GetAsync("/api/v1/agent/listings")).StatusCode);
    }

    [Theory]
    [InlineData("/api/v1/admin/users")]
    [InlineData("/api/v1/admin/keys/rotate")]
    public async Task Admin_routes_exist_and_require_admin(string path)
    {
        var r = await Client(fx.Token("agent")).PostAsync(path, new StringContent("{}"));
        Assert.Equal(HttpStatusCode.Forbidden, r.StatusCode); // 403, not 404: the route is mapped
    }

    [Fact]
    public async Task Invalid_or_revoked_tokens_are_rejected_even_on_public_routes()
    {
        var forged = await Client("not-a-jwt").GetAsync("/api/v1/listings/abc");
        Assert.Equal(HttpStatusCode.Unauthorized, forged.StatusCode);
        Assert.Equal("token_invalid", await ErrorCode(forged));

        var revoked = await Client(fx.Token("agent", jti: "revoked-jti")).GetAsync("/api/v1/agent/listings");
        Assert.Equal(HttpStatusCode.Unauthorized, revoked.StatusCode);
    }

    [Fact]
    public async Task Nl_search_is_rate_limited_with_retry_after()
    {
        var c = Client(fx.Token("buyer", jti: "rate-limit-user"));
        HttpResponseMessage last = null!;
        for (var i = 0; i < 3; i++) last = await c.PostAsync("/api/v1/search/nl", new StringContent("{}"));
        Assert.Equal(HttpStatusCode.TooManyRequests, last.StatusCode);
        Assert.Equal("rate_limited", await ErrorCode(last));
        Assert.True(last.Headers.RetryAfter is not null);
    }

    [Fact]
    public async Task Request_id_is_echoed()
    {
        var req = new HttpRequestMessage(HttpMethod.Get, "/health");
        req.Headers.Add("X-Request-Id", "abc123");
        var r = await Client().SendAsync(req);
        Assert.Equal("abc123", r.Headers.GetValues("X-Request-Id").Single());
    }
}
