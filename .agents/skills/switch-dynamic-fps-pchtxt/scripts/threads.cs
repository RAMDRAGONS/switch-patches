// Guest threads of the application: uid, PC and LR relative to main (`base` hex), several samples.
ulong mbase = System.Convert.ToUInt64((string)ScriptContext.State["base"], 16);
var kc = ctx.Device.System.KernelContext;
var procs = (System.Collections.IDictionary)kc.GetType().GetProperty("Processes", System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance).GetValue(kc);
var sb = new System.Text.StringBuilder();
foreach (System.Collections.DictionaryEntry e in procs) {
  var p = e.Value; var pt = p.GetType();
  string name = (string)pt.GetProperty("Name", System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance)?.GetValue(p);
  var getThreads = pt.GetMethod("GetThreads", System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance);
  if (getThreads == null) continue;
  var threads = (System.Collections.IEnumerable)getThreads.Invoke(p, null);
  foreach (var t in threads) {
    var tt = t.GetType();
    var c = (Ryujinx.Cpu.IExecutionContext)tt.GetProperty("Context").GetValue(t);
    ulong uid = (ulong)tt.GetProperty("ThreadUid").GetValue(t);
    ulong pc = c.Pc, lr = c.GetX(30);
    string r(ulong a) => a >= mbase && a < mbase + 0xD00000 ? $"main+{a - mbase:X}" : $"{a:X}";
    if (pc == 0) continue;
    var mem = (Ryujinx.Memory.IVirtualMemoryManager)pt.GetProperty("CpuMemory", System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance).GetValue(p);
    var chain = new System.Collections.Generic.List<string>();
    ulong fp = c.GetX(29);
    for (int i = 0; i < 16 && fp != 0; i++) {
      ulong nfp, ra;
      try { nfp = mem.Read<ulong>(fp); ra = mem.Read<ulong>(fp + 8); } catch { break; }
      if (ra >= mbase && ra < mbase + 0xD00000) chain.Add(r(ra));
      fp = nfp;
    }
    sb.AppendLine($"t{uid} lr={r(lr)} | {string.Join(" < ", chain)}");
  }
}
return sb.ToString();
