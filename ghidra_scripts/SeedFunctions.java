// Pre-script: disassemble and create a function at every seg:off listed in the seeds file (arg 0).
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import java.nio.file.*;

public class SeedFunctions extends GhidraScript {
    public void run() throws Exception {
        int ok = 0, bad = 0;
        for (String line : Files.readAllLines(Paths.get(getScriptArgs()[0]))) {
            line = line.trim(); if (line.isEmpty()) continue;
            Address a = currentProgram.getAddressFactory().getAddress(line);
            if (a == null) { bad++; continue; }
            new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
            if (getFunctionAt(a) == null && createFunction(a, null) == null) bad++; else ok++;
        }
        println("seeded " + ok + " functions, " + bad + " failed");
    }
}
