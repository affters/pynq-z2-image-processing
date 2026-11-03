`timescale 1ns/1ps

// Streaming gray8 3x3 filters. Only the inner (W-2)*(H-2) pixels are output.
// frame_start and mode describe the input frame; frame_start takes effect
// only when in_valid && in_ready. The mode must remain stable within a frame.
module gray_filter_3x3 #(
    parameter integer IMAGE_WIDTH = 128,
    parameter integer IMAGE_HEIGHT = 96
) (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] in_gray,
    input  wire       in_valid,
    output wire       in_ready,
    input  wire       frame_start,
    input  wire [1:0] mode,
    output reg  [7:0] out_gray,
    output reg        out_valid,
    input  wire       out_ready,
    output reg        out_sof,
    output reg        out_eol
);
    localparam integer COL_BITS = (IMAGE_WIDTH > 1) ? $clog2(IMAGE_WIDTH) : 1;
    localparam integer ROW_BITS = (IMAGE_HEIGHT > 1) ? $clog2(IMAGE_HEIGHT) : 1;

    reg [COL_BITS-1:0] column;
    reg [ROW_BITS-1:0] row;
    wire [COL_BITS-1:0] active_column = frame_start ? {COL_BITS{1'b0}} : column;
    wire [ROW_BITS-1:0] active_row = frame_start ? {ROW_BITS{1'b0}} : row;

    // Each accepted pixel shifts one column through two previous rows.
    // No reset loop: the first two rows of each frame refill the memories
    // before any output becomes valid.
    reg [7:0] previous_row [0:IMAGE_WIDTH-1];
    reg [7:0] older_row [0:IMAGE_WIDTH-1];
    wire [7:0] middle_pixel = previous_row[active_column];
    wire [7:0] top_pixel = older_row[active_column];

    reg [7:0] top_left2, top_left1;
    reg [7:0] middle_left2, middle_left1;
    reg [7:0] bottom_left2, bottom_left1;

    wire [7:0] p00 = top_left2;
    wire [7:0] p01 = top_left1;
    wire [7:0] p02 = top_pixel;
    wire [7:0] p10 = middle_left2;
    wire [7:0] p11 = middle_left1;
    wire [7:0] p12 = middle_pixel;
    wire [7:0] p20 = bottom_left2;
    wire [7:0] p21 = bottom_left1;
    wire [7:0] p22 = in_gray;

    // Gaussian: maximum rounded numerator is 16*255+8 = 4088 (12 bits).
    wire [11:0] gaussian_sum =
        {4'b0,p00} + ({4'b0,p01} << 1) + {4'b0,p02} +
        ({4'b0,p10} << 1) + ({4'b0,p11} << 2) + ({4'b0,p12} << 1) +
        {4'b0,p20} + ({4'b0,p21} << 1) + {4'b0,p22} + 12'd8;

    // Each Sobel gradient lies in [-1020,1020]. Use signed 12-bit terms
    // throughout, then a 13-bit unsigned sum of absolute values.
    wire signed [11:0] sobel_gx =
        $signed({4'b0,p02}) + ($signed({4'b0,p12}) <<< 1) + $signed({4'b0,p22}) -
        $signed({4'b0,p00}) - ($signed({4'b0,p10}) <<< 1) - $signed({4'b0,p20});
    wire signed [11:0] sobel_gy =
        $signed({4'b0,p20}) + ($signed({4'b0,p21}) <<< 1) + $signed({4'b0,p22}) -
        $signed({4'b0,p00}) - ($signed({4'b0,p01}) <<< 1) - $signed({4'b0,p02});
    wire [11:0] sobel_abs_x = sobel_gx[11] ? -sobel_gx : sobel_gx;
    wire [11:0] sobel_abs_y = sobel_gy[11] ? -sobel_gy : sobel_gy;
    wire [12:0] sobel_magnitude = {1'b0,sobel_abs_x} + {1'b0,sobel_abs_y};
    wire [12:0] sobel_scaled = sobel_magnitude >> 2;

    // The sharpening expression lies in [-1020,1275].
    wire signed [12:0] sharpen_value =
        $signed({5'b0,p11}) * 13'sd5 - $signed({5'b0,p01}) -
        $signed({5'b0,p10}) - $signed({5'b0,p12}) - $signed({5'b0,p21});

    reg [7:0] filtered_pixel;
    always @* begin
        case (mode)
            2'd0: filtered_pixel = p11;
            2'd1: filtered_pixel = gaussian_sum[11:4];
            2'd2: filtered_pixel = (sobel_scaled > 13'd255) ? 8'd255 : sobel_scaled[7:0];
            2'd3: begin
                if (sharpen_value < 13'sd0)
                    filtered_pixel = 8'd0;
                else if (sharpen_value > 13'sd255)
                    filtered_pixel = 8'd255;
                else
                    filtered_pixel = sharpen_value[7:0];
            end
            default: filtered_pixel = 8'd0;
        endcase
    end

    // A blocked output freezes coordinates, both line memories, and every
    // window register. Consuming an output may refill the register at once.
    assign in_ready = !rst && (!out_valid || out_ready);

    always @(posedge clk) begin
        if (rst) begin
            column <= {COL_BITS{1'b0}};
            row <= {ROW_BITS{1'b0}};
            top_left2 <= 8'd0;
            top_left1 <= 8'd0;
            middle_left2 <= 8'd0;
            middle_left1 <= 8'd0;
            bottom_left2 <= 8'd0;
            bottom_left1 <= 8'd0;
            out_gray <= 8'd0;
            out_valid <= 1'b0;
            out_sof <= 1'b0;
            out_eol <= 1'b0;
        end else if (in_ready) begin
            out_valid <= 1'b0;
            out_sof <= 1'b0;
            out_eol <= 1'b0;
            if (in_valid) begin
                older_row[active_column] <= middle_pixel;
                previous_row[active_column] <= in_gray;

                if (active_column == 0) begin
                    top_left2 <= 8'd0;
                    middle_left2 <= 8'd0;
                    bottom_left2 <= 8'd0;
                end else begin
                    top_left2 <= top_left1;
                    middle_left2 <= middle_left1;
                    bottom_left2 <= bottom_left1;
                end
                top_left1 <= top_pixel;
                middle_left1 <= middle_pixel;
                bottom_left1 <= in_gray;

                if (active_column == IMAGE_WIDTH-1) begin
                    column <= {COL_BITS{1'b0}};
                    if (active_row == IMAGE_HEIGHT-1)
                        row <= {ROW_BITS{1'b0}};
                    else
                        row <= active_row + 1'b1;
                end else begin
                    column <= active_column + 1'b1;
                    row <= active_row;
                end

                if (active_row >= 2 && active_column >= 2) begin
                    out_gray <= filtered_pixel;
                    out_valid <= 1'b1;
                    out_sof <= (active_row == 2 && active_column == 2);
                    out_eol <= (active_column == IMAGE_WIDTH-1);
                end
            end
        end
    end
endmodule
