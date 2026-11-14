// Emulated display refresh: hz=<N> paces vsync at N Hz, hz=unbounded removes pacing, hz=restore puts back the saved setting.
var d = ctx.Device; string hz = (string)ScriptContext.State["hz"];
if (!ScriptContext.State.ContainsKey("rr_old")) { ScriptContext.State["rr_old"] = d.RefreshRate; ScriptContext.State["rr_unb"] = d.UnboundedFrameRate; }
if (hz == "restore") { d.SetRefreshRate((int)ScriptContext.State["rr_old"], (bool)ScriptContext.State["rr_unb"]); ScriptContext.State.Remove("rr_old", out _); }
else if (hz == "unbounded") d.SetRefreshRate(d.RefreshRate, true);
else d.SetRefreshRate(int.Parse(hz), false);
return $"{d.VSyncMode} {d.RefreshRate} unbounded={d.UnboundedFrameRate}";
