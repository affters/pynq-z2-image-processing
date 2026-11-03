`timescale 1ns/1ps

// One RGB888 pixel per 32-bit AXI stream word. This module is the stream
// datapath/control adapter, not an AXI-Lite register slave.
// control[2:0]: 0=gray, 1=Gaussian, 2=Sobel, 3=sharpen, 4=equalize.
// control[8]: start rising edge while idle. control[9]: synchronous reset.
// status[0]: busy; [1]: sticky done (cleared by accepted start);
// [2]: sticky protocol/mode error (cleared only by reset).
module image_axis_core #(
    parameter integer IMAGE_WIDTH = 128,
    parameter integer IMAGE_HEIGHT = 96
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME clk, ASSOCIATED_BUSIF S_AXIS:M_AXIS, ASSOCIATED_RESET resetn, FREQ_HZ 50000000" *)
    input wire clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME resetn, POLARITY ACTIVE_LOW" *)
    input wire resetn,
    input wire [31:0] control,
    output wire [31:0] status,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXIS, TDATA_NUM_BYTES 4, HAS_TKEEP 1, HAS_TLAST 1, HAS_TREADY 1, HAS_TSTRB 0, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0" *)
    input wire [31:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *)
    input wire [3:0] s_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *)
    input wire s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *)
    output wire s_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *)
    input wire s_axis_tlast,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME M_AXIS, TDATA_NUM_BYTES 4, HAS_TKEEP 1, HAS_TLAST 1, HAS_TREADY 1, HAS_TSTRB 0, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0" *)
    output wire [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *)
    output wire [3:0] m_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *)
    output wire m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *)
    input wire m_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *)
    output wire m_axis_tlast
);
    localparam integer FRAME_PIXELS = IMAGE_WIDTH * IMAGE_HEIGHT;
    localparam integer INNER_PIXELS = (IMAGE_WIDTH-2) * (IMAGE_HEIGHT-2);
    localparam integer COUNT_BITS = (FRAME_PIXELS > 1) ? $clog2(FRAME_PIXELS+1) : 1;
    localparam [COUNT_BITS-1:0] FULL_COUNT = FRAME_PIXELS;
    localparam [COUNT_BITS-1:0] INNER_COUNT = INNER_PIXELS;

    reg busy, done, error;
    reg start_previous;
    reg [2:0] active_mode;
    reg equalize_start;
    reg [COUNT_BITS-1:0] input_count, gray_count, output_count;
    wire reset_active = !resetn || control[9];
    wire core_reset = reset_active || !busy;
    wire start_edge = control[8] && !start_previous;
    wire window_selected = (active_mode >= 1 && active_mode <= 3);
    wire equalize_selected = (active_mode == 4);
    wire [COUNT_BITS-1:0] output_limit = window_selected ? INNER_COUNT : FULL_COUNT;

    wire [7:0] gray_pixel;
    wire gray_valid, gray_input_ready;
    wire gray_ready;
    wire [7:0] window_pixel, equalize_pixel;
    wire window_valid, window_input_ready;
    wire equalize_valid, equalize_input_ready;
    wire window_output_ready = busy && !reset_active && window_selected && m_axis_tready;
    wire equalize_output_ready = busy && !reset_active && equalize_selected && m_axis_tready;
    wire [7:0] selected_pixel = window_selected ? window_pixel :
                                equalize_selected ? equalize_pixel : gray_pixel;
    wire selected_valid = window_selected ? window_valid :
                          equalize_selected ? equalize_valid : gray_valid;

    assign status = {29'd0, error, done, busy};
    assign s_axis_tready = busy && !reset_active && (input_count < FULL_COUNT) && gray_input_ready;
    assign gray_ready = busy && !reset_active &&
                        (window_selected ? window_input_ready :
                         equalize_selected ? equalize_input_ready : m_axis_tready);
    assign m_axis_tdata = {24'd0, selected_pixel};
    assign m_axis_tkeep = 4'b1111;
    assign m_axis_tvalid = busy && !reset_active && selected_valid;
    assign m_axis_tlast = m_axis_tvalid && (output_count == output_limit-1'b1);

    rgb_to_gray gray_core (
        .clk(clk), .rst(core_reset), .in_rgb(s_axis_tdata[23:0]),
        .in_valid(s_axis_tvalid && busy && !reset_active && input_count < FULL_COUNT),
        .in_ready(gray_input_ready), .out_gray(gray_pixel),
        .out_valid(gray_valid), .out_ready(gray_ready)
    );

    gray_filter_3x3 #(.IMAGE_WIDTH(IMAGE_WIDTH), .IMAGE_HEIGHT(IMAGE_HEIGHT)) window_core (
        .clk(clk), .rst(core_reset), .in_gray(gray_pixel),
        .in_valid(gray_valid && busy && window_selected),
        .in_ready(window_input_ready), .frame_start(gray_count == 0),
        .mode(active_mode[1:0]), .out_gray(window_pixel), .out_valid(window_valid),
        .out_ready(window_output_ready), .out_sof(), .out_eol()
    );

    frame_equalize #(.IMAGE_WIDTH(IMAGE_WIDTH), .IMAGE_HEIGHT(IMAGE_HEIGHT)) equalize_core (
        .clk(clk), .rst(core_reset), .start(equalize_start),
        .busy(), .done(), .in_gray(gray_pixel),
        .in_valid(gray_valid && busy && equalize_selected),
        .in_ready(equalize_input_ready), .out_gray(equalize_pixel),
        .out_valid(equalize_valid), .out_ready(equalize_output_ready)
    );

    always @(posedge clk) begin
        if (reset_active) begin
            busy <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            start_previous <= 1'b0;
            active_mode <= 3'd0;
            equalize_start <= 1'b0;
            input_count <= {COUNT_BITS{1'b0}};
            gray_count <= {COUNT_BITS{1'b0}};
            output_count <= {COUNT_BITS{1'b0}};
        end else begin
            start_previous <= control[8];
            equalize_start <= 1'b0;
            if (start_edge && !busy) begin
                if (control[2:0] > 4) begin
                    error <= 1'b1;
                end else begin
                    active_mode <= control[2:0];
                    busy <= 1'b1;
                    done <= 1'b0;
                    input_count <= {COUNT_BITS{1'b0}};
                    gray_count <= {COUNT_BITS{1'b0}};
                    output_count <= {COUNT_BITS{1'b0}};
                    // Children are reset while idle at this edge. This
                    // pulse is therefore sampled by HE on the next edge,
                    // after its reset is released and mode is latched.
                    equalize_start <= (control[2:0] == 4);
                end
            end

            if (s_axis_tvalid && s_axis_tready) begin
                input_count <= input_count + 1'b1;
                if (s_axis_tlast != (input_count == FULL_COUNT-1'b1) ||
                    s_axis_tkeep != 4'b1111)
                    error <= 1'b1;
            end
            if (gray_valid && gray_ready)
                gray_count <= gray_count + 1'b1;
            if (m_axis_tvalid && m_axis_tready) begin
                output_count <= output_count + 1'b1;
                if (output_count == output_limit-1'b1) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end
            end
        end
    end
endmodule
