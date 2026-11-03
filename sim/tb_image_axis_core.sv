`timescale 1ns/1ps

// count.txt is one full RGB frame, not a batch count. Reference files are
// expected_mode0.hex through expected_mode4.hex. Modes 1..3 are cropped.
module tb_image_axis_core #(
    parameter integer IMAGE_WIDTH = 128,
    parameter integer IMAGE_HEIGHT = 96
);
    localparam integer MAX_INPUTS = 65536;
    localparam integer FRAME_PIXELS = IMAGE_WIDTH*IMAGE_HEIGHT;
    localparam integer INNER_PIXELS = (IMAGE_WIDTH-2)*(IMAGE_HEIGHT-2);

    reg clk = 0;
    reg resetn = 0;
    reg [31:0] control = 0;
    wire [31:0] status;
    reg [31:0] s_axis_tdata = 0;
    reg [3:0] s_axis_tkeep = 4'hf;
    reg s_axis_tvalid = 0, s_axis_tlast = 0;
    wire s_axis_tready;
    wire [31:0] m_axis_tdata;
    wire [3:0] m_axis_tkeep;
    wire m_axis_tvalid, m_axis_tlast;
    reg m_axis_tready = 0;

    reg [23:0] input_rgb [0:MAX_INPUTS-1];
    reg [7:0] expected0 [0:MAX_INPUTS-1];
    reg [7:0] expected1 [0:MAX_INPUTS-1];
    reg [7:0] expected2 [0:MAX_INPUTS-1];
    reg [7:0] expected3 [0:MAX_INPUTS-1];
    reg [7:0] expected4 [0:MAX_INPUTS-1];
    integer file_width, file_height, file_count, index;
    integer test_mode, expected_outputs, sent, received;
    integer result_file = 0;
    integer completed_frames = 0;
    reg checking_frame = 0;
    reg allow_unchecked_output = 0;
    reg input_stalled = 0, output_stalled = 0;
    reg [31:0] held_input, held_output;
    reg [3:0] held_input_keep, held_output_keep;
    reg held_input_last, held_output_last;

    image_axis_core #(.IMAGE_WIDTH(IMAGE_WIDTH), .IMAGE_HEIGHT(IMAGE_HEIGHT)) dut (
        .clk(clk), .resetn(resetn), .control(control), .status(status),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready), .s_axis_tlast(s_axis_tlast),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready), .m_axis_tlast(m_axis_tlast)
    );
    always #5 clk = ~clk;

    task automatic read_integer_file(input string name, output integer value);
        integer handle, scanned;
        begin
            handle = $fopen(name, "r");
            if (!handle) $fatal(1, "cannot open %s", name);
            scanned = $fscanf(handle, "%d", value);
            $fclose(handle);
            if (scanned != 1) $fatal(1, "invalid integer in %s", name);
        end
    endtask

    function automatic [7:0] reference_pixel(input integer selected_mode, input integer pixel_index);
        begin
            case (selected_mode)
                0: reference_pixel = expected0[pixel_index];
                1: reference_pixel = expected1[pixel_index];
                2: reference_pixel = expected2[pixel_index];
                3: reference_pixel = expected3[pixel_index];
                4: reference_pixel = expected4[pixel_index];
                default: reference_pixel = 8'hxx;
            endcase
        end
    endfunction

    task automatic tick(
        input bit next_resetn, input [31:0] next_control,
        input bit next_valid, input [31:0] next_data,
        input [3:0] next_keep, input bit next_last, input bit next_ready
    );
        reg stalled_now, finished_now;
        reg [31:0] output_before;
        reg [3:0] keep_before;
        reg last_before;
        begin
            @(negedge clk);
            resetn = next_resetn;
            control = next_control;
            s_axis_tvalid = next_valid;
            s_axis_tdata = next_data;
            s_axis_tkeep = next_keep;
            s_axis_tlast = next_last;
            m_axis_tready = next_ready;
            #1;
            if ((!resetn || control[9]) &&
                (s_axis_tready !== 0 || m_axis_tvalid !== 0))
                $fatal(1, "stream handshakes were not blocked during reset");

            @(posedge clk);
            stalled_now = m_axis_tvalid && !m_axis_tready;
            output_before = m_axis_tdata;
            keep_before = m_axis_tkeep;
            last_before = m_axis_tlast;
            finished_now = 0;
            if (!resetn || control[9]) begin
                input_stalled = 0;
                output_stalled = 0;
            end else begin
                if (s_axis_tready !== 0 && s_axis_tready !== 1)
                    $fatal(1, "input ready contains X/Z");
                if (m_axis_tvalid !== 0 && m_axis_tvalid !== 1)
                    $fatal(1, "output valid contains X/Z");
                if (input_stalled &&
                    (!s_axis_tvalid || s_axis_tdata !== held_input ||
                     s_axis_tkeep !== held_input_keep || s_axis_tlast !== held_input_last))
                    $fatal(1, "testbench changed a blocked input");
                if (output_stalled &&
                    (!m_axis_tvalid || m_axis_tdata !== held_output ||
                     m_axis_tkeep !== held_output_keep || m_axis_tlast !== held_output_last))
                    $fatal(1, "output changed before stalled word was consumed");

                if (m_axis_tvalid) begin
                    if (m_axis_tdata[31:8] !== 24'd0 || m_axis_tkeep !== 4'hf)
                        $fatal(1, "output padding or TKEEP is incorrect");
                    if (checking_frame) begin
                        if (received >= expected_outputs)
                            $fatal(1, "extra output mode=%0d", test_mode);
                        if (m_axis_tdata[7:0] !== reference_pixel(test_mode, received))
                            $fatal(1, "pixel mismatch mode=%0d index=%0d got=%02x expected=%02x",
                                   test_mode, received, m_axis_tdata[7:0], reference_pixel(test_mode, received));
                        if (m_axis_tlast !== (received == expected_outputs-1))
                            $fatal(1, "output TLAST mismatch mode=%0d index=%0d", test_mode, received);
                    end else if (!allow_unchecked_output)
                        $fatal(1, "unexpected output outside a frame");
                end
                if (checking_frame && m_axis_tvalid && m_axis_tready) begin
                    if (result_file) $fdisplay(result_file, "%02x", m_axis_tdata[7:0]);
                    received = received+1;
                    finished_now = (received == expected_outputs);
                end
                if (checking_frame && s_axis_tvalid && s_axis_tready) begin
                    if (sent >= FRAME_PIXELS || s_axis_tdata[23:0] !== input_rgb[sent])
                        $fatal(1, "input index/data mismatch mode=%0d index=%0d", test_mode, sent);
                    sent = sent+1;
                end
                input_stalled = s_axis_tvalid && !s_axis_tready;
                held_input = s_axis_tdata;
                held_input_keep = s_axis_tkeep;
                held_input_last = s_axis_tlast;
                output_stalled = stalled_now;
                held_output = output_before;
                held_output_keep = keep_before;
                held_output_last = last_before;
            end
            #1;
            if (!resetn || control[9]) begin
                if (status !== 32'd0 || s_axis_tready !== 0 || m_axis_tvalid !== 0)
                    $fatal(1, "reset failed to clear control/stream state");
            end else begin
                if (status[31:3] !== 0) $fatal(1, "reserved status bits are not zero");
                if (!status[0] && (s_axis_tready !== 0 || m_axis_tvalid !== 0))
                    $fatal(1, "idle core is accepting or producing data");
                if (stalled_now &&
                    (m_axis_tvalid !== 1 || m_axis_tdata !== output_before ||
                     m_axis_tkeep !== keep_before || m_axis_tlast !== last_before))
                    $fatal(1, "AXI output changed under backpressure");
                if (checking_frame) begin
                    if (finished_now) begin
                        if (status[0] !== 0 || status[1] !== 1 || sent != FRAME_PIXELS)
                            $fatal(1, "completion did not follow the final output handshake");
                    end else if (status[0] !== 1 || status[1] !== 0)
                        $fatal(1, "busy/done changed before the final output handshake");
                end
            end
        end
    endtask

    task automatic idle(input [31:0] word);
        begin tick(1, word, 0, 0, 4'hf, 0, 1); end
    endtask
    task automatic soft_reset;
        begin
            checking_frame = 0;
            tick(1, 32'h00000200, 1, 32'h00ffffff, 4'hf, 1, 1);
            idle(0);
            idle(0);
            if (status !== 0) $fatal(1, "software reset left stale status");
        end
    endtask

    // fault: 0=good, 1=early TLAST, 2=missing final TLAST, 3=bad TKEEP.
    task automatic run_frame(
        input integer requested_mode, input bit export_result,
        input integer fault, input bit expected_error
    );
        integer cycles;
        reg [31:0] random_state, control_word, data_word;
        reg valid_word, ready_word, last_word;
        reg [3:0] keep_word;
        string output_name;
        begin
            if (status[0]) $fatal(1, "cannot begin test while busy");
            idle(requested_mode);
            test_mode = requested_mode;
            expected_outputs = (requested_mode >= 1 && requested_mode <= 3) ? INNER_PIXELS : FRAME_PIXELS;
            sent = 0;
            received = 0;
            idle(32'h00000100 | requested_mode);
            if (status[0] !== 1 || status[1] !== 0)
                $fatal(1, "start was not accepted or did not clear done");
            if (export_result) begin
                output_name = $sformatf("rtl_axis_mode%0d.hex", requested_mode);
                result_file = $fopen(output_name, "w");
                if (!result_file) $fatal(1, "cannot create %s", output_name);
            end
            checking_frame = 1;
            cycles = 0;
            random_state = 32'h3a57c91d ^ requested_mode;
            while (sent < FRAME_PIXELS || received < expected_outputs) begin
                if (cycles > FRAME_PIXELS*100+16384)
                    $fatal(1, "timeout mode=%0d sent=%0d received=%0d", test_mode, sent, received);
                random_state = {random_state[30:0],
                                random_state[31] ^ random_state[21] ^ random_state[1] ^ random_state[0]};
                // Change control mode and issue another rising start while
                // busy. Both must leave the active frame configuration alone.
                control_word = (cycles >= 4) ? 32'h00000107 : 32'h00000007;
                ready_word = (cycles < 8) ? 1'b1 :
                             (cycles < 24) ? 1'b0 : (random_state[2] || random_state[5]);
                if (input_stalled) begin
                    valid_word = 1;
                    data_word = held_input;
                    keep_word = held_input_keep;
                    last_word = held_input_last;
                end else if (sent < FRAME_PIXELS) begin
                    valid_word = (cycles < 32) || random_state[0] || random_state[3];
                    data_word = {8'd0, input_rgb[sent]};
                    keep_word = (fault == 3 && sent == 0) ? 4'h7 : 4'hf;
                    last_word = (sent == FRAME_PIXELS-1);
                    if (fault == 1 && sent == 0) last_word = 1;
                    if (fault == 2 && sent == FRAME_PIXELS-1) last_word = 0;
                    if (!valid_word) last_word = 1;
                end else begin
                    valid_word = 0;
                    data_word = 0;
                    keep_word = 4'hf;
                    last_word = 1;
                end
                tick(1, control_word, valid_word, data_word, keep_word, last_word, ready_word);
                cycles = cycles+1;
            end
            if (sent != FRAME_PIXELS || received != expected_outputs || status[2] !== expected_error)
                $fatal(1, "frame count/error status mismatch mode=%0d status=%08x", test_mode, status);
            checking_frame = 0;
            if (result_file) begin
                $fclose(result_file);
                result_file = 0;
            end
            completed_frames = completed_frames+1;
            // A busy-time start held high after completion must not restart.
            idle(32'h00000107);
            idle(32'h00000107);
            if (status[0] !== 0 || status[1] !== 1 || status[2] !== expected_error)
                $fatal(1, "done/error was not sticky, or held start retriggered");
        end
    endtask

    initial begin
        if (IMAGE_WIDTH < 3 || IMAGE_HEIGHT < 3 || FRAME_PIXELS > MAX_INPUTS)
            $fatal(1, "invalid test dimensions");
        read_integer_file("width.txt", file_width);
        read_integer_file("height.txt", file_height);
        read_integer_file("count.txt", file_count);
        if (file_width != IMAGE_WIDTH || file_height != IMAGE_HEIGHT || file_count != FRAME_PIXELS)
            $fatal(1, "fixture dimensions/count do not match elaborated testbench");
        $readmemh("input_rgb.hex", input_rgb, 0, FRAME_PIXELS-1);
        $readmemh("expected_mode0.hex", expected0, 0, FRAME_PIXELS-1);
        $readmemh("expected_mode1.hex", expected1, 0, INNER_PIXELS-1);
        $readmemh("expected_mode2.hex", expected2, 0, INNER_PIXELS-1);
        $readmemh("expected_mode3.hex", expected3, 0, INNER_PIXELS-1);
        $readmemh("expected_mode4.hex", expected4, 0, FRAME_PIXELS-1);
        for (index = 0; index < FRAME_PIXELS; index = index+1) begin
            if ((^input_rgb[index]) === 1'bx || (^expected0[index]) === 1'bx ||
                (^expected4[index]) === 1'bx)
                $fatal(1, "missing full-frame fixture index=%0d", index);
        end
        for (index = 0; index < INNER_PIXELS; index = index+1)
            if ((^expected1[index]) === 1'bx || (^expected2[index]) === 1'bx ||
                (^expected3[index]) === 1'bx)
                $fatal(1, "missing cropped fixture index=%0d", index);

        tick(0, 0, 0, 0, 4'hf, 0, 0);
        tick(0, 0, 0, 0, 4'hf, 0, 0);
        tick(1, 0, 1, 32'h00123456, 4'hf, 1, 1);
        if (s_axis_tready !== 0 || status !== 0) $fatal(1, "input accepted before start");
        // Drop the unaccepted idle word using reset, which invalidates it.
        soft_reset();
        idle(32'h00000105);
        if (status !== 32'h4) $fatal(1, "illegal mode was not rejected");
        idle(32'h00000100);
        if (status !== 32'h4) $fatal(1, "held start created a new rising edge");
        soft_reset();

        run_frame(0, 1, 0, 0);
        run_frame(1, 1, 0, 0);
        run_frame(2, 1, 0, 0);
        run_frame(3, 1, 0, 0);
        run_frame(4, 1, 0, 0);
        run_frame(0, 0, 0, 0);
        soft_reset();
        run_frame(0, 0, 1, 1);
        run_frame(1, 0, 0, 1);
        soft_reset();
        run_frame(0, 0, 2, 1);
        soft_reset();
        run_frame(0, 0, 3, 1);
        soft_reset();

        // Reset a valid output blocked by the sink and a blocked next input.
        allow_unchecked_output = 1;
        idle(32'h00000100);
        tick(1, 0, 1, 0, 4'hf, 0, 0);
        repeat (8) tick(1, 0, 1, 32'h00ffffff, 4'hf, 0, 0);
        if (m_axis_tvalid !== 1 || status[0] !== 1)
            $fatal(1, "reset test did not create a pending output");
        soft_reset();
        allow_unchecked_output = 0;
        // External reset also cancels an HE operation before any input.
        idle(32'h00000104);
        tick(0, 0, 0, 0, 4'hf, 0, 1);
        idle(0);
        idle(0);
        if (status !== 0 || m_axis_tvalid !== 0) $fatal(1, "external reset left stale work");
        $display("SIM_PASS image_axis_core modes=5 frames=%0d", completed_frames);
        $finish;
    end

    initial begin
        repeat (MAX_INPUTS*200+262144) @(posedge clk);
        $fatal(1, "global image AXI simulation timeout");
    end
endmodule
