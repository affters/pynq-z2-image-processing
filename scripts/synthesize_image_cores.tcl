# Out-of-context synthesis estimates only. No implementation or programming.
# Resolve source paths inside the runner's ASCII staging copy.
set project_root [file normalize [file join [file dirname [info script]] ..]]
set output_root [file join $project_root output synthesis]
set target_part xc7z020clg400-1
set core_names {rgb_to_gray gray_filter_3x3 frame_equalize}
set rtl_sources [concat \
    [glob -nocomplain [file join $project_root rtl *.v]] \
    [glob -nocomplain [file join $project_root rtl *.sv]]]

set_param general.maxThreads 2
puts "SYNTHESIS_ESTIMATES_ONLY part=$target_part clock_period_ns=10.000"
puts "No placement, routing, bitstream generation, or hardware programming."

if {[catch {
    if {[llength $rtl_sources] == 0} {
        error "No RTL sources found under [file join $project_root rtl]"
    }
    file mkdir $output_root

    # Each core is synthesized alone, in sequence, with default parameters.
    foreach core $core_names {
        set output_dir [file join $output_root $core]
        file mkdir $output_dir
        puts "SYNTH_CORE_START $core"
        create_project -in_memory -part $target_part
        read_verilog -sv $rtl_sources

        # An ideal, zero-delay external source/sink is an estimation
        # assumption, not a board interface constraint. Read it before
        # synthesis so the 10 ns target also guides synthesis optimization.
        set clock_file [file join $output_dir synthesis_clock.xdc]
        set handle [open $clock_file w]
        puts $handle {create_clock -name core_clk -period 10.000 [get_ports clk]}
        puts $handle {set_input_delay -clock [get_clocks core_clk] -max 0.000 [get_ports -filter {DIRECTION == IN && NAME != clk}]}
        puts $handle {set_input_delay -clock [get_clocks core_clk] -min 0.000 [get_ports -filter {DIRECTION == IN && NAME != clk}]}
        puts $handle {set_output_delay -clock [get_clocks core_clk] -max 0.000 [all_outputs]}
        puts $handle {set_output_delay -clock [get_clocks core_clk] -min 0.000 [all_outputs]}
        close $handle
        read_xdc $clock_file

        synth_design -mode out_of_context -top $core -part $target_part
        if {[llength [get_clocks core_clk]] != 1} {
            error "Expected one constrained core_clk for $core"
        }
        report_utilization -file [file join $output_dir utilization.rpt]

        set timing_file [file join $output_dir timing_estimate.rpt]
        set handle [open $timing_file w]
        puts $handle "OUT-OF-CONTEXT SYNTHESIS ESTIMATE ONLY"
        puts $handle "Core: $core"
        puts $handle "Part: $target_part"
        puts $handle "Parameters: RTL defaults (128 x 96 for image-sized cores)."
        puts $handle "Clock target: 10.000 ns (100 MHz constraint, not an achieved frequency)."
        puts $handle "External input/output delay assumption: 0.000 ns."
        puts $handle "No placement, routing, pin assignment, or hardware timing measurement."
        puts $handle "No top-level clock buffer location: clock insertion delay/skew is not estimated."
        puts $handle "Use implementation and board measurements for final performance claims."
        puts $handle ""
        close $handle
        report_timing_summary -delay_type max -max_paths 10 -report_unconstrained \
            -file $timing_file -append
        write_checkpoint -force [file join $output_dir ${core}_synthesized.dcp]
        close_project
        puts "SYNTH_CORE_OK $core"
    }
} failure]} {
    puts stderr "SYNTHESIS_FAILED: $failure"
    catch {close_project}
    exit 1
}

puts "SYNTHESIS_ALL_OK estimates_only=1 cores=3 clock_period_ns=10.000"
exit 0
