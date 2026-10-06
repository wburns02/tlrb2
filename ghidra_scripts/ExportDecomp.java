import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class ExportDecomp extends GhidraScript {
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        new File(out).mkdirs();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter idx = new PrintWriter(new FileWriter(out + "/_functions.tsv"));
        PrintWriter all = new PrintWriter(new FileWriter(out + "/_all.c"));
        idx.println("addr\tname\tsize\tcallers\tcallees");
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int n = 0;
        while (it.hasNext() && !monitor.isCancelled()) {
            Function f = it.next();
            if (f.isThunk()) continue;
            Set<String> callers = new TreeSet<>();
            for (Function c : f.getCallingFunctions(monitor)) callers.add(c.getEntryPoint().toString());
            Set<String> callees = new TreeSet<>();
            for (Function c : f.getCalledFunctions(monitor)) callees.add(c.getEntryPoint().toString());
            DecompileResults r = di.decompileFunction(f, 30, monitor);
            String code = r.decompileCompleted() ? r.getDecompiledFunction().getC() : "/* decompile failed */";
            idx.println(f.getEntryPoint() + "\t" + f.getName() + "\t" + f.getBody().getNumAddresses() + "\t" + String.join(",", callers) + "\t" + String.join(",", callees));
            all.println("// ==== " + f.getEntryPoint() + " " + f.getName() + " callers=" + callers);
            all.println(code);
            n++;
        }
        idx.close(); all.close();
        println("exported " + n);
    }
}
