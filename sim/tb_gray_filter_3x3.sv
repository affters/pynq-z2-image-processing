`timescale 1ns/1ps

// Override these top-level parameters in xelab for a small-size run.
// width.txt/height.txt must match the elaborated dimensions.
module tb_gray_filter_3x3 #(
    parameter integer IMAGE_WIDTH = 128,
    parameter integer IMAGE_HEIGHT = 96
);
    localparam integer MAX_INPUTS = 65536;
    localparam integer FRAME_PIXELS = IMAGE_WIDTH * IMAGE_HEIGHT;
    localparam integer INNER_WIDTH = IMAGE_WIDTH - 2;
    localparam integer OUTPUTS_PER_FRAME = INNER_WIDTH * (IMAGE_HEIGHT - 2);

    reg clk = 1'b0;
    reg rst = 1'b1;
    reg [7:0] in_gray = 8'd0;
    reg in_valid = 1'b0;
    wire in_ready;
    reg frame_start = 1'b0;
    reg [1:0] mode = 2'd0;
    wire [7:0] out_gray;
    wire out_valid;
    reg out_ready = 1'b0;
    wire out_sof, out_eol;

    reg [7:0] input_pixels [0:MAX_INPUTS-1];
    reg [7:0] expected_pixels [0:MAX_INPUTS-1];
    integer input_count, expected_count, frame_count;
    integer file_width, file_height, file_mode;
    integer output_file;
    integer accepted_count = 0;
    integer enqueued_count = 0;
    integer produced_count = 0;
    integer model_column = 0;
    integer model_row = 0;
    integer main_cycle = 0;
    integer timeout_cycles;
    integer index;
    reg main_phase = 1'b0;
    reg input_stalled = 1'b0;
    reg [7:0] held_input;
    reg held_frame_start;
    reg output_stalled = 1'b0;
    reg [7:0] held_output;
    reg held_sof, held_eol;
    reg next_valid, next_ready, next_frame_start;
    reg [7:0] next_pixel;

    gray_filter_3x3 #(
        .IMAGE_WIDTH(IMAGE_WIDTH), .IMAGE_HEIGHT(IMAGE_HEIGHT)
    ) dut (
        .clk(clk), .rst(rst),
        .in_gray(in_gray), .in_valid(in_valid), .in_ready(in_ready),
        .frame_start(frame_start), .mode(mode),
        .out_gray(out_gray), .out_valid(out_valid), .out_ready(out_ready),
        .out_sof(out_sof), .out_eol(out_eol)
    );

    always #5 clk = ~clk;

    task automatic read_integer_file(input string name, output integer value);
        integer handle, status;
        begin
            handle = $fopen(name, "r");
            if (handle == 0)
                $fatal(1, "cannot open %s", name);
            status = $fscanf(handle, "%d", value);
            $fclose(handle);
            if (status != 1)
                $fatal(1, "invalid integer in %s", name);
        end
    endtask

    // Stimulus is changed only on falling edges; the scoreboard samples
    // handshakes before DUT nonblocking updates at the next rising edge.
    task automatic step(
        input bit reset_value,
        input bit valid_value,
        input [7:0] pixel_value,
        input bit start_value,
        input bit ready_value
    );
        reg stalled_at_edge;
        reg [7:0] gray_at_edge, wanted_gray;
        reg sof_at_edge, eol_at_edge, wanted_sof, wanted_eol;
        integer current_column, current_row;
        begin
            @(negedge clk);
            rst = reset_value;
            in_valid = valid_value;
            in_gray = pixel_value;
            frame_start = start_value;
            out_ready = ready_value;
            #1;
            if (rst && in_ready !== 1'b0)
                $fatal(1, "in_ready must be low during reset");

            @(posedge clk);
            stalled_at_edge = out_valid && !out_ready;
            gray_at_edge = out_gray;
            sof_at_edge = out_sof;
            eol_at_edge = out_eol;
            if (rst) begin
                accepted_count = 0;
                enqueued_count = 0;
                produced_count = 0;
                model_column = 0;
                model_row = 0;
                input_stalled = 1'b0;
                output_stalled = 1'b0;
            end else begin
                if (in_ready !== 1'b0 && in_ready !== 1'b1)
                    $fatal(1, "in_ready contains X/Z");
                if (out_valid !== 1'b0 && out_valid !== 1'b1)
                    $fatal(1, "out_valid contains X/Z");
                if (stalled_at_edge && in_ready !== 1'b0)
                    $fatal(1, "input was not frozen while output was blocked");
                if (input_stalled &&
                    (in_valid !== 1'b1 || in_gray !== held_input ||
                     frame_start !== held_frame_start))
                    $fatal(1, "testbench changed stalled input data or frame_start");
                if (output_stalled &&
                    (out_valid !== 1'b1 || out_gray !== held_output ||
                     out_sof !== held_sof || out_eol !== held_eol))
                    $fatal(1, "output data or metadata changed before consumption");

                if (out_valid) begin
                    if (produced_count >= enqueued_count)
                        $fatal(1, "unexpected/duplicate output index=%0d", produced_count);
                    if (main_phase)
                        wanted_gray = expected_pixels[produced_count];
                    else
                        wanted_gray = (mode == 2) ? 8'd0 : 8'd128;
                    wanted_sof = (produced_count % OUTPUTS_PER_FRAME == 0);
                    wanted_eol = (produced_count % INNER_WIDTH == INNER_WIDTH-1);
                    if (out_gray !== wanted_gray)
                        $fatal(1, "pixel mismatch phase=%0d index=%0d got=%02x expected=%02x",
                               main_phase, produced_count, out_gray, wanted_gray);
                    if (out_sof !== wanted_sof || out_eol !== wanted_eol)
                        $fatal(1, "metadata mismatch index=%0d sof=%b/%b eol=%b/%b",
                               produced_count, out_sof, wanted_sof, out_eol, wanted_eol);
                end
                if (out_valid && out_ready) begin
                    if (main_phase)
                        $fdisplay(output_file, "%02x", out_gray);
                    produced_count = produced_count + 1;
                end

                if (in_valid && in_ready) begin
                    if (main_phase) begin
                        if (accepted_count >= input_count)
                            $fatal(1, "accepted an extra input");
                        if (in_gray !== input_pixels[accepted_count])
                            $fatal(1, "input order mismatch index=%0d", accepted_count);
                        if (frame_start !== (accepted_count % FRAME_PIXELS == 0))
                            $fatal(1, "input frame_start mismatch index=%0d", accepted_count);
                    end
                    current_column = frame_start ? 0 : model_column;
                    current_row = frame_start ? 0 : model_row;
                    if (current_column >= 2 && current_row >= 2)
                        enqueued_count = enqueued_count + 1;
                    if (current_column == IMAGE_WIDTH-1) begin
                        model_column = 0;
                        model_row = (current_row == IMAGE_HEIGHT-1) ? 0 : current_row+1;
                    end else begin
                        model_column = current_column+1;
                        model_row = current_row;
                    end
                    accepted_count = accepted_count + 1;
                end
                if (enqueued_count - produced_count < 0 ||
                    enqueued_count - produced_count > 1)
                    $fatal(1, "elastic output capacity violated: queued=%0d received=%0d",
                           enqueued_count, produced_count);
                input_stalled = in_valid && !in_ready;
                held_input = in_gray;
                held_frame_start = frame_start;
                output_stalled = stalled_at_edge;
                held_output = gray_at_edge;
                held_sof = sof_at_edge;
                held_eol = eol_at_edge;
            end

            #1;
            if (rst) begin
                if (out_valid !== 1'b0 || in_ready !== 1'b0 ||
                    out_sof !== 1'b0 || out_eol !== 1'b0)
                    $fatal(1, "reset failed to clear output state");
            end else if (stalled_at_edge) begin
                if (out_valid !== 1'b1 || out_gray !== gray_at_edge ||
                    out_sof !== sof_at_edge || out_eol !== eol_at_edge)
                    $fatal(1, "output register changed under backpressure");
            end
        end
    endtask

    initial begin
        if (IMAGE_WIDTH < 3 || IMAGE_HEIGHT < 3)
            $fatal(1, "both dimensions must be at least 3");
        read_integer_file("count.txt", input_count);
        read_integer_file("width.txt", file_width);
        read_integer_file("height.txt", file_height);
        read_integer_file("mode.txt", file_mode);
        if (file_width != IMAGE_WIDTH || file_height != IMAGE_HEIGHT)
            $fatal(1, "file dimensions %0dx%0d differ from elaborated %0dx%0d",
                   file_width, file_height, IMAGE_WIDTH, IMAGE_HEIGHT);
        if (file_mode < 0 || file_mode > 3)
            $fatal(1, "mode.txt must be in 0..3");
        mode = file_mode;
        if (input_count < 2*FRAME_PIXELS || input_count > MAX_INPUTS ||
            input_count % FRAME_PIXELS != 0)
            $fatal(1, "count.txt must describe at least two complete frames, at most %0d pixels",
                   MAX_INPUTS);
        frame_count = input_count / FRAME_PIXELS;
        expected_count = frame_count * OUTPUTS_PER_FRAME;
        $readmemh("input_gray.hex", input_pixels, 0, input_count-1);
        $readmemh("expected_gray.hex", expected_pixels, 0, expected_count-1);
        for (index = 0; index < input_count; index = index+1)
            if ((^input_pixels[index]) === 1'bx)
                $fatal(1, "missing or unknown input vector index=%0d", index);
        for (index = 0; index < expected_count; index = index+1)
            if ((^expected_pixels[index]) === 1'bx)
                $fatal(1, "missing or unknown expected vector index=%0d", index);
        output_file = $fopen("rtl_filter.hex", "w");
        if (output_file == 0)
            $fatal(1, "cannot create rtl_filter.hex");

        step(1, 0, 8'd0, 0, 0);
        step(1, 0, 8'd0, 0, 0);
        // Prime two rows and three pixels of a uniform frame. This makes
        // exactly one output pending, without consuming it. An invalid
        // frame_start pulse midway must not restart the coordinate state.
        for (index = 0; index < 2*IMAGE_WIDTH+3; index = index+1) begin
            if (index == IMAGE_WIDTH+1)
                step(0, 0, 8'd128, 1, 0);
            step(0, 1, 8'd128, index == 0, 0);
        end
        if (accepted_count != 2*IMAGE_WIDTH+3 || enqueued_count != 1 || produced_count != 0)
            $fatal(1, "directed priming count mismatch");
        repeat (12) step(0, 1, 8'd128, 0, 0);
        // With both a pending output and a blocked input, reset must drop
        // both. The line RAM remains dirty and is refilled by the main run.
        step(1, 1, 8'd128, 0, 1);
        step(0, 0, 8'd0, 0, 1);
        step(0, 0, 8'd0, 0, 1);
        if (accepted_count != 0 || enqueued_count != 0 || produced_count != 0 || out_valid !== 0)
            $fatal(1, "reset failed to discard pending work");

        main_phase = 1'b1;
        timeout_cycles = input_count*40+1024;
        while (accepted_count < input_count || produced_count < expected_count) begin
            if (main_cycle >= timeout_cycles)
                $fatal(1, "timeout: accepted=%0d/%0d produced=%0d/%0d",
                       accepted_count, input_count, produced_count, expected_count);
            if (main_cycle < 3*IMAGE_WIDTH+16)
                next_ready = 1'b1;
            else if (main_cycle < 3*IMAGE_WIDTH+40)
                next_ready = 1'b0;
            else
                next_ready = (main_cycle % 23 >= 9);

            if (input_stalled) begin
                next_valid = 1'b1;
                next_pixel = held_input;
                next_frame_start = held_frame_start;
            end else if (accepted_count < input_count) begin
                next_valid = (main_cycle < 3*IMAGE_WIDTH+16) ||
                             (main_cycle % 13 < 4) || (main_cycle % 13 > 6);
                next_pixel = input_pixels[accepted_count];
                next_frame_start = (accepted_count % FRAME_PIXELS == 0);
                // Inactive sideband pulses must be ignored.
                if (!next_valid)
                    next_frame_start = 1'b1;
            end else begin
                next_valid = 1'b0;
                next_pixel = 8'd0;
                next_frame_start = 1'b0;
            end
            step(0, next_valid, next_pixel, next_frame_start, next_ready);
            main_cycle = main_cycle+1;
        end
        if (accepted_count != input_count || enqueued_count != expected_count ||
            produced_count != expected_count)
            $fatal(1, "final frame or output count mismatch");
        repeat (3) step(0, 0, 8'd0, 0, 1);
        $fclose(output_file);
        $display("SIM_PASS gray_filter_3x3 count=%0d", produced_count);
        $finish;
    end

    initial begin
        repeat (MAX_INPUTS*40+4096) @(posedge clk);
        $fatal(1, "global simulation timeout");
    end
endmodule
