# Volatile no-OS image test. No SD/QSPI/eFUSE writes.
# The launcher verifies bit, PS initialization and firmware before calling.
if {$argc != 3} {error "Expected image_system.bit, matching ps7_init.tcl, uart_image.elf"}
set bitfile [string map {\\ /} [lindex $argv 0]]
set initfile [string map {\\ /} [lindex $argv 1]]
set firmware [string map {\\ /} [lindex $argv 2]]
foreach f [list $bitfile $initfile $firmware] {
    if {![file isfile $f]} {error "Required input missing: $f"}
    if {![string equal -nocase [file normalize $f] $f]} {
        error "Input path resolves differently; use an unsandboxed Vivado shell before programming"
    }
}
connect -url tcp:127.0.0.1:3121
puts "UART_IMAGE_TARGETS=[targets]"
# Refuse warm PL reconfiguration: an interrupted DMA can leave PS/AXI state.
# Check before stopping CPUs or changing any board registers.
targets -set -filter {name =~ "xc7z020*"}
set initial_pl_state [fpga -state]
puts "UART_IMAGE_INITIAL_PL_STATE=$initial_pl_state"
if {![string match -nocase "*not configured*" $initial_pl_state]} {
    error "FPGA already configured or state uncertain; power-cycle the board before loading"
}
targets -set -filter {name == "APU"}
puts "UART_IMAGE_PRE_BOOT_STATE=[mrd 0xF8000258 2]"
proc stop_if_running {} {
    if {[catch {stop} message options]} {
        if {![string match -nocase "*Already stopped*" $message]} {
            return -options $options $message
        }
    }
}
targets -set -filter {name =~ "ARM*#1"}
stop_if_running
targets -set -filter {name =~ "ARM*#0"}
stop_if_running
rst -processor -stop -clear-registers
targets -set -filter {name =~ "xc7z020*"}
fpga -file $bitfile
puts "UART_IMAGE_FPGA_STATE=[fpga -state]"
targets -set -filter {name =~ "ARM*#0"}
source $initfile
ps7_init
ps7_post_config
puts "UART_IMAGE_PS_INIT_COMPLETE"
dow $firmware
puts "UART_IMAGE_ENTRY=[rrd pc]"
con
after 100
puts "UART_IMAGE_FIRMWARE_STARTED"
disconnect
exit
