// Pre-script: optionally set DS = arg 1 (hex segment, DGROUP) over all memory, then disassemble and create a
// function at every seg:off listed in the seeds file (arg 0).
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import java.nio.file.*;
import java.math.BigInteger;
import ghidra.program.model.lang.Register;
import ghidra.program.model.mem.MemoryBlock;

public class SeedFunctions extends GhidraScript {
    public void run() throws Exception {
        int ok = 0, bad = 0;
        if (getScriptArgs().length > 1) {
            Register ds = currentProgram.getRegister("DS");
            BigInteger v = new BigInteger(getScriptArgs()[1], 16);
            for (MemoryBlock b : currentProgram.getMemory().getBlocks())
                currentProgram.getProgramContext().setValue(ds, b.getStart(), b.getEnd(), v);
            println("DS set to " + getScriptArgs()[1]);
        }
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
