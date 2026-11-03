# One-time completion of interrupted load: PL/PS initialization already passed,
# dow failed before firmware started, so no DMA transfer has been submitted.
set firmware [string map {\\ /} [lindex $argv 0]]
if {![file isfile $firmware]} {error "ELF missing"}
connect -url tcp:127.0.0.1:3121
puts "FINISH_DOWNLOAD_TARGETS=[targets]"
targets -set -filter {name =~ "ARM*#0"}
dow $firmware
puts "FINISH_DOWNLOAD_ENTRY=[rrd pc]"
con
after 100
puts "FINISH_DOWNLOAD_STARTED"
disconnect
exit
