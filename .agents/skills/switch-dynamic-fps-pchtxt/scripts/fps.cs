// Guest frame rate as Ryujinx's status bar shows it, sampled `n` times one second apart (default 3).
int n = ScriptContext.State.ContainsKey("n") ? int.Parse((string)ScriptContext.State["n"]) : 3;
var d = ctx.Device; var sb = new System.Text.StringBuilder();
for (int i = 0; i < n; i++) { System.Threading.Thread.Sleep(1000); sb.Append($"{d.Statistics.GetGameFrameRate():F1} "); }
return $"game fps: {sb}| vsync={d.VSyncMode} refresh={d.RefreshRate}";
