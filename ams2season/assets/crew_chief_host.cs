// Paddock's local radio host. Uses the user's installed MQTTnet; ships no Crew Chief code.
using System;
using System.Collections.Generic;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using MQTTnet;
using MQTTnet.Protocol;
using MQTTnet.Server;

public static class PaddockRadioHost
{
    static readonly object OutputLock = new object();
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static void Emit(object value)
    {
        lock (OutputLock) { Console.WriteLine(Json.Serialize(value)); Console.Out.Flush(); }
    }
    public static void Run(int port, string token, bool allowAudio = false)
    {
        const string topic = "/paddock/coach/Paddock";
        IMqttServer server = null;
        try
        {
            var options = new MqttServerOptionsBuilder().WithDefaultEndpoint()
                .WithDefaultEndpointPort(port)
                .WithDefaultEndpointBoundIPAddress(IPAddress.Loopback)
                .WithDefaultEndpointBoundIPV6Address(IPAddress.IPv6Loopback)
                .WithConnectionBacklog(4).WithMaxPendingMessagesPerClient(4)
                .WithDefaultCommunicationTimeout(TimeSpan.FromSeconds(5))
                .WithConnectionValidator((Action<MqttConnectionValidatorContext>)(ctx => {
                    if (ctx.Username != "paddock" || ctx.Password != token)
                        ctx.ReasonCode = MqttConnectReasonCode.BadUserNameOrPassword;
                }))
                .WithSubscriptionInterceptor((Action<MqttSubscriptionInterceptorContext>)(ctx => {
                    ctx.AcceptSubscription = ctx.TopicFilter.Topic == topic;
                }))
                .WithApplicationMessageInterceptor((Action<MqttApplicationMessageInterceptorContext>)(ctx => {
                    // Client telemetry is neither stored nor forwarded. Only the
                    // host may publish coaching; clients can acknowledge receipt.
                    if (!String.IsNullOrEmpty(ctx.ClientId)) {
                        var msg = ctx.ApplicationMessage;
                        if (msg.Topic == "/paddock/coach/_debug/Paddock" && msg.Payload != null && msg.Payload.Length <= 4096)
                            Emit(new { type = "ack", payload = Encoding.UTF8.GetString(msg.Payload) });
                        ctx.AcceptPublish = false;
                    }
                })).Build();
            server = new MqttFactory().CreateMqttServer();
            server.ClientSubscribedTopicHandler = new MqttServerClientSubscribedTopicHandlerDelegate(
                (Action<MqttServerClientSubscribedTopicEventArgs>)(e => {
                    if (e.TopicFilter.Topic == topic) Emit(new { type = "subscribed", client = e.ClientId });
                }));
            server.UseClientDisconnectedHandler((Action<MqttServerClientDisconnectedEventArgs>)(e =>
                Emit(new { type = "disconnected", client = e.ClientId })));
            server.StartAsync(options).GetAwaiter().GetResult();
            Emit(new { type = "ready", port = port });
            string line;
            int audioPort = 0;
            while ((line = Console.ReadLine()) != null)
            {
                if (line.Length > 8192) continue;
                var command = Json.Deserialize<Dictionary<string, object>>(line);
                if ((string)command["type"] == "stop") break;
                string kind = (string)command["type"];
                if (kind == "bind_audio") {
                    int candidate = Convert.ToInt32(command["port"]);
                    if (allowAudio && candidate >= 1024 && candidate <= 65535) audioPort = candidate;
                    continue;
                }
                bool isAudio = kind == "audio";
                // "speak": a coaching call with no recorded clip, read by CC's TTS in its
                // regular queue. "say" stays the immediate radio check.
                bool isSpeech = kind == "speak";
                if (kind != "say" && !isAudio && !isSpeech) continue;
                if (isSpeech && !allowAudio) continue;
                string text = (string)command[isAudio ? "url" : "text"];
                if (String.IsNullOrWhiteSpace(text) || text.Length > 256) continue;
                if (isAudio) {
                    Uri uri;
                    if (!allowAudio || audioPort == 0 || !Uri.TryCreate(text, UriKind.Absolute, out uri)
                        || uri.Scheme != "http" || uri.Host != "127.0.0.1" || uri.Port != audioPort
                        || !String.IsNullOrEmpty(uri.UserInfo) || !String.IsNullOrEmpty(uri.Query) || !String.IsNullOrEmpty(uri.Fragment)
                        || !Regex.IsMatch(uri.AbsolutePath, @"^/api/coach/audio/[a-f0-9]{48}\.wav$")
                        || text != "http://127.0.0.1:" + audioPort + uri.AbsolutePath) continue;
                } else if (text.StartsWith("http", StringComparison.OrdinalIgnoreCase)) continue;
                // An explicit radio check must wake the audio monitor itself.
                // The regular queue is woken by game ticks. Immediate delivery
                // wakes its monitor, but CC still validates the active session.
                // Coaching audio belongs to CC's ordinary queue. Its spotter has
                // priority, and the one-use clip endpoint revalidates on fetch.
                var payload = Json.Serialize(new { message = text, distance = 0, priority = 0, immediate = kind == "say" });
                var message = new MqttApplicationMessageBuilder().WithTopic(topic)
                    .WithPayload(payload).WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtMostOnce)
                    .WithRetainFlag(false).Build();
                server.PublishAsync(message).GetAwaiter().GetResult();
                Emit(new { type = "sent", id = command["id"] });
            }
        }
        catch (Exception e) { Emit(new { type = "error", error = e.GetType().Name + ": " + e.Message }); }
        finally { if (server != null) { try { server.StopAsync().Wait(2000); } catch {} server.Dispose(); } }
    }
}
