`timescale 1ns/1ps

// The elaborated dimensions must match width.txt/height.txt (or W.txt/H.txt).
// count.txt is the total pixel count, at least two whole frames. Input and
// expected files contain that many gray8 hex values. Only the main vector
// phase is written to rtl_equalize.hex; directed preflight frames are omitted.
module tb_frame_equalize #(
    parameter integer IMAGE_WIDTH = 128,
    parameter integer IMAGE_HEIGHT = 96
);
    localparam integer FRAME_PIXELS = IMAGE_WIDTH * IMAGE_HEIGHT;
    localparam integer MAX_INPUTS = 262144;
    reg clk = 1'b0;
    reg rst = 1'b1;
    reg start = 1'b0;
    wire busy, done;
    reg [7:0] in_gray = 8'd0;
    reg in_valid = 1'b0;
    wire in_ready;
    wire [7:0] out_gray;
    wire out_valid;
    reg out_ready = 1'b0;

    reg [7:0] input_pixels [0:MAX_INPUTS-1];
    reg [7:0] expected_pixels [0:MAX_INPUTS-1];
    integer input_count, file_width, file_height, frame_count;
    integer output_file;
    integer accepted_count = 0, produced_count = 0;
    integer frame_inputs = 0, frame_outputs = 0;
    integer frames_started = 0, frames_completed = 0;
    integer cycle_count = 0, timeout_cycles = 2000000000;
    integer index, frame_index;
    reg frame_active = 1'b0;
    reg main_phase = 1'b0;
    reg input_stalled = 1'b0, output_stalled = 1'b0;
    reg [7:0] held_input, held_output;

    frame_equalize #(
        .IMAGE_WIDTH(IMAGE_WIDTH), .IMAGE_HEIGHT(IMAGE_HEIGHT)
    ) dut (
        .clk(clk), .rst(rst), .start(start), .busy(busy), .done(done),
        .in_gray(in_gray), .in_valid(in_valid), .in_ready(in_ready),
        .out_gray(out_gray), .out_valid(out_valid), .out_ready(out_ready)
    );
    always #5 clk = ~clk;

    task automatic read_integer_file(input string name, output integer value);
        integer handle, status, extra;
        begin
            handle = $fopen(name, "r");
            if (!handle) $fatal(1, "cannot open %s", name);
            status = $fscanf(handle, "%d", value);
            if (status != 1) $fatal(1, "invalid integer in %s", name);
            status = $fscanf(handle, "%d", extra);
            if (status != -1) $fatal(1, "unexpected trailing data in %s", name);
            $fclose(handle);
        end
    endtask

    task automatic read_dimension(
        input string canonical, input string alternate, output integer value
    );
        integer handle;
        begin
            handle = $fopen(canonical, "r");
            if (handle) begin
                $fclose(handle);
                read_integer_file(canonical, value);
            end else
                read_integer_file(alternate, value);
        end
    endtask

    task automatic read_vectors(input string name, input bit expected_file);
        integer handle, status, n;
        reg [31:0] value;
        begin
            handle = $fopen(name, "r");
            if (!handle) $fatal(1, "cannot open %s", name);
            for (n = 0; n < input_count; n = n+1) begin
                status = $fscanf(handle, "%h", value);
                if (status != 1 || (^value) === 1'bx || value > 255)
                    $fatal(1, "invalid/missing gray8 value %0d in %s", n, name);
                if (expected_file) expected_pixels[n] = value[7:0];
                else input_pixels[n] = value[7:0];
            end
            status = $fscanf(handle, "%h", value);
            if (status != -1) $fatal(1, "extra/malformed data after count in %s", name);
            $fclose(handle);
        end
    endtask

    // Drive on falling edges and score handshakes before DUT NBA updates.
    task automatic step(
        input bit reset_value, input bit start_value, input bit valid_value,
        input [7:0] pixel_value, input bit ready_value
    );
        reg last_transfer, blocked_at_edge;
        reg [7:0] edge_pixel, wanted;
        begin
            @(negedge clk);
            rst = reset_value;
            start = start_value;
            in_valid = valid_value;
            in_gray = pixel_value;
            out_ready = ready_value;
            @(posedge clk);
            cycle_count = cycle_count + 1;
            if (cycle_count > timeout_cycles)
                $fatal(1, "timeout accepted=%0d produced=%0d active=%0d", accepted_count,
                       produced_count, frame_active);
            last_transfer = 1'b0;
            blocked_at_edge = out_valid && !out_ready;
            edge_pixel = out_gray;
            if (rst) begin
                accepted_count = 0;
                produced_count = 0;
                frame_inputs = 0;
                frame_outputs = 0;
                frames_started = 0;
                frames_completed = 0;
                frame_active = 1'b0;
                input_stalled = 1'b0;
                output_stalled = 1'b0;
            end else begin
                if ((busy !== 0 && busy !== 1) || (done !== 0 && done !== 1) ||
                    (in_ready !== 0 && in_ready !== 1) ||
                    (out_valid !== 0 && out_valid !== 1))
                    $fatal(1, "control output contains X/Z");
                if (!busy && in_ready !== 0)
                    $fatal(1, "idle must refuse input");
                if (busy !== frame_active)
                    $fatal(1, "busy disagrees with active frame");
                if (output_stalled && (out_valid !== 1 || out_gray !== held_output))
                    $fatal(1, "output changed before consumption");
                if (input_stalled && (in_valid !== 1 || in_gray !== held_input))
                    $fatal(1, "testbench changed a held input");

                if (start && !busy) begin
                    if (frame_active) $fatal(1, "overlapping accepted starts");
                    frame_active = 1'b1;
                    frame_inputs = 0;
                    frame_outputs = 0;
                    frames_started = frames_started+1;
                end
                if (in_valid && in_ready) begin
                    if (!frame_active || frame_inputs >= FRAME_PIXELS)
                        $fatal(1, "unexpected/extra accepted input");
                    if (main_phase && (accepted_count >= input_count ||
                        in_gray !== input_pixels[accepted_count]))
                        $fatal(1, "input order mismatch index=%0d", accepted_count);
                    accepted_count = accepted_count+1;
                    frame_inputs = frame_inputs+1;
                end
                if (out_valid) begin
                    if (!frame_active || frame_inputs != FRAME_PIXELS ||
                        frame_outputs >= FRAME_PIXELS)
                        $fatal(1, "early/extra output");
                    if (main_phase) begin
                        if (produced_count >= input_count)
                            $fatal(1, "extra main output");
                        wanted = expected_pixels[produced_count];
                    end else wanted = 8'd73;
                    if (out_gray !== wanted)
                        $fatal(1, "pixel mismatch phase=%0d index=%0d got=%02x expected=%02x",
                               main_phase, produced_count, out_gray, wanted);
                end
                if (out_valid && out_ready) begin
                    if (main_phase) $fdisplay(output_file, "%02x", out_gray);
                    produced_count = produced_count+1;
                    frame_outputs = frame_outputs+1;
                    if (frame_outputs == FRAME_PIXELS) begin
                        last_transfer = 1'b1;
                        frame_active = 1'b0;
                        frames_completed = frames_completed+1;
                    end
                end
                // Only an active producer in the input phase needs to hold
                // its pixel; deliberate garbage while idle is ignored.
                input_stalled = in_valid && !in_ready && frame_active &&
                                frame_inputs < FRAME_PIXELS;
                held_input = in_gray;
                output_stalled = blocked_at_edge;
                held_output = edge_pixel;
            end
            #1;
            if (rst) begin
                if (busy !== 0 || done !== 0 || out_valid !== 0 || in_ready !== 0)
                    $fatal(1, "synchronous reset did not clear control state");
            end else begin
                if (done !== last_transfer)
                    $fatal(1, "done must pulse only after the final output handshake");
                if (busy !== frame_active)
                    $fatal(1, "busy transition mismatch");
                if (blocked_at_edge && (out_valid !== 1 || out_gray !== edge_pixel))
                    $fatal(1, "output changed under backpressure");
            end
        end
    endtask

    task automatic run_frame;
        integer first_stall, final_stall;
        reg next_valid, next_ready;
        reg [7:0] next_pixel;
        begin
            step(0, 1, 0, 8'd0, 0);
            while (frame_inputs < FRAME_PIXELS) begin
                next_valid = input_stalled || (cycle_count % 13 < 9);
                next_pixel = main_phase ? input_pixels[accepted_count] : 8'd73;
                step(0, busy && (cycle_count % 17 == 3), next_valid, next_pixel, 0);
            end
            first_stall = 48;
            final_stall = 32;
            while (frame_active) begin
                if (out_valid && first_stall > 0) begin
                    next_ready = 0;
                    first_stall = first_stall-1;
                end else if (out_valid && frame_outputs == FRAME_PIXELS-1 && final_stall > 0) begin
                    next_ready = 0;
                    final_stall = final_stall-1;
                end else
                    next_ready = (first_stall == 0) && (cycle_count % 19 >= 6);
                step(0, busy && (cycle_count % 23 == 5), 0, 8'd0, next_ready);
            end
            if (frame_inputs != FRAME_PIXELS || frame_outputs != FRAME_PIXELS || done !== 1)
                $fatal(1, "frame completion count mismatch");
            // Garbage while idle must neither be accepted nor create output.
            step(0, 0, 1, 8'hc7, 1);
            step(0, 0, 0, 8'd0, 1);
        end
    endtask

    initial begin
        if (IMAGE_WIDTH < 1 || IMAGE_HEIGHT < 1)
            $fatal(1, "dimensions must be positive");
        read_integer_file("count.txt", input_count);
        read_dimension("width.txt", "W.txt", file_width);
        read_dimension("height.txt", "H.txt", file_height);
        if (file_width != IMAGE_WIDTH || file_height != IMAGE_HEIGHT)
            $fatal(1, "file dimensions %0dx%0d differ from elaborated %0dx%0d",
                   file_width, file_height, IMAGE_WIDTH, IMAGE_HEIGHT);
        if (input_count < 2*FRAME_PIXELS || input_count > MAX_INPUTS ||
            input_count % FRAME_PIXELS != 0)
            $fatal(1, "count must contain at least two complete frames, at most %0d pixels",
                   MAX_INPUTS);
        frame_count = input_count / FRAME_PIXELS;
        timeout_cycles = (frame_count+2)*(FRAME_PIXELS*16+4096)+4096;
        read_vectors("input_gray.hex", 0);
        read_vectors("expected_gray.hex", 1);
        output_file = $fopen("rtl_equalize.hex", "w");
        if (!output_file) $fatal(1, "cannot create rtl_equalize.hex");

        step(1, 0, 0, 0, 0);
        step(1, 0, 0, 0, 0);
        step(0, 0, 1, 8'hff, 1);
        if (accepted_count != 0 || produced_count != 0)
            $fatal(1, "idle accepted data");
        // Uniform frame verifies d=0 preserves gray level. Both first and
        // final outputs are blocked; busy-time starts must be ignored.
        run_frame();
        if (frames_started != 1 || frames_completed != 1)
            $fatal(1, "busy-time start caused an extra frame");

        // Dirty part of the frame/histogram, then abort synchronously.
        // The main run must clear this history without resetting RAM arrays.
        step(0, 1, 0, 0, 0);
        while (!in_ready) step(0, 0, 0, 0, 0);
        for (index = 0; index < ((FRAME_PIXELS < 7) ? FRAME_PIXELS : 7); index = index+1)
            step(0, 0, 1, 8'hff, 0);
        step(1, 1, 1, 8'hff, 1);
        step(0, 0, 0, 0, 1);
        main_phase = 1'b1;
        for (frame_index = 0; frame_index < frame_count; frame_index = frame_index+1)
            run_frame();
        if (accepted_count != input_count || produced_count != input_count ||
            frames_started != frame_count || frames_completed != frame_count)
            $fatal(1, "final count mismatch accepted=%0d produced=%0d starts=%0d done=%0d",
                   accepted_count, produced_count, frames_started, frames_completed);
        repeat (5) step(0, 0, 0, 0, 1);
        $fclose(output_file);
        $display("SIM_PASS frame_equalize count=%0d", produced_count);
        $finish;
    end
endmodule
