# Temporary FPGA configuration and volatile DDR/MMIO only. No SD/QSPI writes.
# Usage: xsdb test_image_system_jtag.tcl <bit> <ps7_init.tcl> <fixtures> <xsa>
if {$argc != 4} {error "Expected bitstream, matching ps7_init.tcl, fixture directory, XSA"}
# The launcher supplies absolute paths. Avoid Tcl 8.5 Windows file normalize:
# in this sandbox it drops hidden directory components despite readable files.
set bitfile [string map {\\ /} [lindex $argv 0]]
set initfile [string map {\\ /} [lindex $argv 1]]
set fixture [string map {\\ /} [lindex $argv 2]]
set xsafile [string map {\\ /} [lindex $argv 3]]
foreach p [list $bitfile $initfile $fixture $xsafile] {
    if {[file pathtype $p] ne "absolute"} {error "Launcher must supply absolute paths"}
}
foreach f [list $bitfile $initfile $xsafile "$fixture/cases.tcl"] {
    if {![file isfile $f]} {error "Required file missing: $f"}
}
set idfile [open "$fixture/run_id.txt" r]
set run_id [string trim [read $idfile]]
close $idfile
if {![regexp {^[0-9a-f]{32}$} $run_id]} {error "Missing current-run identity"}
connect -url tcp:127.0.0.1:3121
puts [targets]
# -set fails if the selected name is absent or ambiguous.
targets -set -filter {name == "APU"}
puts "PRE_INIT_REBOOT_STATUS=[mrd 0xF8000258 2]"
# This is a dedicated no-OS test. Stop both CPUs before changing PS/DDR setup.
proc stop_cpu {} {
    if {[catch {stop} message options]} {
        if {![string match -nocase "*Already stopped*" $message]} {
            return -options $options $message
        }
    }
}
targets -set -filter {name =~ "ARM*#1"}
stop_cpu
targets -set -filter {name =~ "ARM*#0"}
stop_cpu
targets -set -filter {name =~ "xc7z020*"}
fpga -file $bitfile
puts "FPGA_STATE=[fpga -state]"
targets -set -filter {name =~ "ARM*#0"}
source $initfile
ps7_init
ps7_post_config
puts "PS7_INIT_OK"
# XSDB checks PL windows on the parent memory context. Register them on APU,
# not only on the child ARM#0 context (as confirmed by XSDB set_memmap code).
targets -set -filter {name == "APU"}
if {[llength [info commands ::hsi::open_hw_design]]} {
    loadhw -hw $xsafile
    puts "HARDWARE_ADDRESS_MAP_LOADED_FROM_XSA"
} else {
    # Vivado-only XSDB lacks the Vitis HSI library. The launcher verifies these
    # exact two base addresses against the generated HWH before connecting.
    # Register only those two RW peripheral ranges, not arbitrary PL memory.
    memmap -addr 0x40400000 -size 0x10000 -flags 3
    memmap -addr 0x41200000 -size 0x10000 -flags 3
    puts "HARDWARE_ADDRESS_MAP_HWH_VERIFIED_TWO_RANGES=[memmap -list]"
}

set input_address 0x10000000
set output_address 0x11000000
set dma 0x40400000
set gpio 0x41200000
proc read32 {address} {return [lindex [mrd -value $address] 0]}
proc wait_mask {address mask expected timeout_ms label} {
    set deadline [expr {[clock milliseconds]+$timeout_ms}]
    while {1} {
        set value [read32 $address]
        if {($value & $mask) == $expected} {return $value}
        if {[clock milliseconds] > $deadline} {error "$label timed out value=$value"}
        after 2
    }
}
# DDR scratch check at exactly the two explicitly reserved test buffers.
foreach address [list $input_address $output_address] {
    mwr $address {0x12345678 0x89abcdef 0x00000000 0xffffffff}
    set values [mrd -value $address 4]
    set expected {0x12345678 0x89abcdef 0x00000000 0xffffffff}
    foreach actual $values golden $expected {
        if {$actual != $golden} {error "DDR scratch readback mismatch at $address"}
    }
}
puts "DDR_SCRATCH_PASS"
mwr [expr {$gpio+4}] 0
mwr [expr {$gpio+12}] 0xffffffff
mwr $gpio 0x200
after 2
mwr $gpio 0
mwr $dma 4
wait_mask $dma 4 0 2000 "DMA reset"
mwr $dma 1
mwr [expr {$dma+0x30}] 1

source "$fixture/cases.tcl"
set completed 0
set result [catch {
    foreach item $image_cases {
        lassign $item name mode input_file input_pixels output_pixels
        if {$input_pixels != 12288 || $output_pixels ni {12288 11844}} {
            error "Unexpected fixture dimensions"
        }
        mwr -bin -file "$fixture/$input_file" $input_address $input_pixels
        # Fill output with a marker so a missing DMA write cannot look valid.
        mwr $output_address 0xdeadbeef $output_pixels
        mwr $gpio [expr {$mode|0x100}]
        mwr $gpio $mode
        # Arm receive before send. Byte counts are four times pixel counts.
        mwr [expr {$dma+0x48}] $output_address
        mwr [expr {$dma+0x4c}] 0
        mwr [expr {$dma+0x58}] [expr {$output_pixels*4}]
        mwr [expr {$dma+0x18}] $input_address
        mwr [expr {$dma+0x1c}] 0
        mwr [expr {$dma+0x28}] [expr {$input_pixels*4}]
        set deadline [expr {[clock milliseconds]+10000}]
        while {1} {
            set status [read32 [expr {$gpio+8}]]
            set tx [read32 [expr {$dma+4}]]
            set rx [read32 [expr {$dma+0x34}]]
            if {($status & 4) || (($tx|$rx) & 0x70)} {
                error "Core/DMA error name=$name core=$status tx=$tx rx=$rx"
            }
            if {($status & 3) == 2 && ($tx & 2) && ($rx & 2)} {break}
            if {[clock milliseconds] > $deadline} {
                error "Frame timed out name=$name core=$status tx=$tx rx=$rx"
            }
            after 2
        }
        set received_bytes [read32 [expr {$dma+0x58}]]
        if {$received_bytes != $output_pixels*4} {error "DMA output length mismatch $name"}
        mrd -bin -file "$fixture/${name}_actual.bin" $output_address $output_pixels
        incr completed
        puts "JTAG_FRAME_DONE name=$name output_pixels=$output_pixels core=$status tx=$tx rx=$rx"
    }
} message options]
# Always quiesce the test. CPUs remain halted; no Linux was started.
catch {mwr $gpio 0x200}
catch {mwr $dma 4}
if {$result} {return -options $options $message}
puts "JTAG_IMAGE_PASS run_id=$run_id cases=$completed"
disconnect
exit
