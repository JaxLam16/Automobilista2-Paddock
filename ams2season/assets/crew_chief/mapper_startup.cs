// Runtime preparation only: never maps or triggers fabricated telemetry.
using System;using System.Reflection;using System.Runtime.CompilerServices;
public static class PaddockMapperStartup {
    public static void Prepare() {
        var resolver=Newtonsoft.Json.JsonSerializer.CreateDefault().ContractResolver;
        foreach(var type in typeof(PaddockMapperHost).Assembly.GetTypes()) {
            if(type.ContainsGenericParameters)continue;
            foreach(var method in type.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Static|BindingFlags.Instance|BindingFlags.DeclaredOnly)) {
                if(method.IsAbstract || method.ContainsGenericParameters || method.GetMethodBody()==null)continue;
                RuntimeHelpers.PrepareMethod(method.MethodHandle);
            }
            // Prime reflection contracts used by raw structs, snapshots and
            // event diagnostics without constructing a game-state sample.
            if(type.IsValueType || type.Name.StartsWith("<>f__AnonymousType"))resolver.ResolveContract(type);
        }
    }
}
