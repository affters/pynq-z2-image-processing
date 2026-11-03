`timescale 1ns/1ps

// RGB888 {R,G,B} to gray8 with one elastic output register.
// gray = (77*R + 150*G + 29*B + 128) >> 8.
module rgb_to_gray (
    input  wire        clk,
    input  wire        rst,
    input  wire [23:0] in_rgb,
    input  wire        in_valid,
    output wire        in_ready,
    output reg  [7:0]  out_gray,
    output reg         out_valid,
    input  wire        out_ready
);
    // Explicitly widen both operands. The largest rounded sum is
    // (77 + 150 + 29)*255 + 128 = 65408, which fits in 16 bits.
    wire [15:0] weighted_r = {8'b0, in_rgb[23:16]} * 16'd77;
    wire [15:0] weighted_g = {8'b0, in_rgb[15:8]}  * 16'd150;
    wire [15:0] weighted_b = {8'b0, in_rgb[7:0]}   * 16'd29;
    wire [15:0] rounded_sum = weighted_r + weighted_g + weighted_b + 16'd128;

    assign in_ready = !rst && (!out_valid || out_ready);

    always @(posedge clk) begin
        if (rst) begin
            out_valid <= 1'b0;
            out_gray  <= 8'd0;
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid)
                out_gray <= rounded_sum[15:8];
        end
    end
endmodule
