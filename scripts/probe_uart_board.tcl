# Read-only PS boot/UART mux and PL configuration check. No CPU stop/reset.
connect -url tcp:127.0.0.1:3121
puts "RESUME_TARGETS=[targets]"
targets -set -filter {name == "APU"}
puts "RESUME_BOOT=[mrd 0xF8000258 2]"
puts "RESUME_UART_MUX=[mrd 0xF8000738 2]"
targets -set -filter {name =~ "xc7z020*"}
puts "RESUME_PL_STATE=[fpga -state]"
puts "RESUME_READ_ONLY_COMPLETE"
disconnect
exit
