`timescale 1ns/1ps

// Frame-buffered gray8 histogram equalization, entirely in PL.
// start is accepted only in idle. Input and output each contain exactly
// IMAGE_WIDTH*IMAGE_HEIGHT accepted pixels per frame. The output path uses
// three stages (RAM read, LUT lookup, handshake), not one pixel per clock.
module frame_equalize #(
    parameter integer IMAGE_WIDTH = 128,
    parameter integer IMAGE_HEIGHT = 96
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    output reg        busy,
    output reg        done,
    input  wire [7:0] in_gray,
    input  wire       in_valid,
    output wire       in_ready,
    output reg  [7:0] out_gray,
    output reg        out_valid,
    input  wire       out_ready
);
    localparam integer FRAME_PIXELS = IMAGE_WIDTH * IMAGE_HEIGHT;
    localparam integer ADDR_BITS = (FRAME_PIXELS > 1) ? $clog2(FRAME_PIXELS) : 1;
    localparam integer COUNT_BITS = (FRAME_PIXELS > 1) ? $clog2(FRAME_PIXELS+1) : 1;
    // delta*255 + floor(d/2) is below 2**(COUNT_BITS+8).
    localparam integer NUM_BITS = COUNT_BITS + 8;
    localparam [COUNT_BITS-1:0] TOTAL_PIXELS = FRAME_PIXELS;

    localparam [3:0] IDLE = 4'd0, CLEAR_HIST = 4'd1, RECEIVE = 4'd2,
                     FIND_MIN = 4'd3, LUT_PREP = 4'd4, DIVIDE = 4'd5,
                     LUT_NEXT = 4'd6, OUTPUT_READ = 4'd7,
                     OUTPUT_LOOKUP = 4'd8, OUTPUT_SEND = 4'd9;
    reg [3:0] state;
    reg [7:0] bin_index;
    reg [ADDR_BITS-1:0] write_address, read_address;

    // Frame storage has synchronous read/write and no element-wise reset.
    (* ram_style = "block" *) reg [7:0] frame_ram [0:FRAME_PIXELS-1];
    reg [7:0] frame_pixel;
    // The 256-bin counter bank uses an asynchronous read/modify/write.
    // This is intentionally separate from the synchronous frame RAM.
    reg [COUNT_BITS-1:0] histogram [0:255];
    reg [7:0] equalize_lut [0:255];
    reg [COUNT_BITS-1:0] cdf, cdf_min, denominator;
    wire [COUNT_BITS-1:0] cdf_next = cdf + histogram[bin_index];
    wire [COUNT_BITS-1:0] delta = cdf_next - cdf_min;
    wire [NUM_BITS-1:0] delta_extended = {{8{1'b0}}, delta};
    wire [NUM_BITS-1:0] denominator_extended = {{8{1'b0}}, denominator};
    wire [NUM_BITS-1:0] rounded_numerator =
        (delta_extended << 8) - delta_extended + (denominator_extended >> 1);

    reg [NUM_BITS-1:0] remainder;
    reg [7:0] quotient;
    reg [2:0] division_bit;
    wire [NUM_BITS-1:0] trial = denominator_extended << division_bit;
    wire trial_fits = remainder >= trial;
    wire [7:0] quotient_next = trial_fits ?
        (quotient | (8'b00000001 << division_bit)) : quotient;

    assign in_ready = !rst && (state == RECEIVE);

    always @(posedge clk) begin
        if (!rst) begin
            if (in_valid && in_ready)
                frame_ram[write_address] <= in_gray;
            if (state == OUTPUT_READ)
                frame_pixel <= frame_ram[read_address];
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            out_valid <= 1'b0;
            out_gray <= 8'd0;
            bin_index <= 8'd0;
            write_address <= {ADDR_BITS{1'b0}};
            read_address <= {ADDR_BITS{1'b0}};
            cdf <= {COUNT_BITS{1'b0}};
            cdf_min <= {COUNT_BITS{1'b0}};
            denominator <= {COUNT_BITS{1'b0}};
            remainder <= {NUM_BITS{1'b0}};
            quotient <= 8'd0;
            division_bit <= 3'd0;
        end else begin
            done <= 1'b0;
            case (state)
                IDLE: begin
                    out_valid <= 1'b0;
                    if (start) begin
                        busy <= 1'b1;
                        bin_index <= 8'd0;
                        write_address <= {ADDR_BITS{1'b0}};
                        state <= CLEAR_HIST;
                    end
                end
                CLEAR_HIST: begin
                    histogram[bin_index] <= {COUNT_BITS{1'b0}};
                    if (bin_index == 8'd255) begin
                        bin_index <= 8'd0;
                        state <= RECEIVE;
                    end else
                        bin_index <= bin_index + 1'b1;
                end
                RECEIVE: begin
                    if (in_valid && in_ready) begin
                        histogram[in_gray] <= histogram[in_gray] + 1'b1;
                        if (write_address == FRAME_PIXELS-1) begin
                            bin_index <= 8'd0;
                            state <= FIND_MIN;
                        end else
                            write_address <= write_address + 1'b1;
                    end
                end
                FIND_MIN: begin
                    // Before this first nonzero bin the accumulated CDF is zero.
                    if (histogram[bin_index] != 0) begin
                        cdf_min <= histogram[bin_index];
                        denominator <= TOTAL_PIXELS - histogram[bin_index];
                        cdf <= {COUNT_BITS{1'b0}};
                        bin_index <= 8'd0;
                        state <= LUT_PREP;
                    end else
                        bin_index <= bin_index + 1'b1;
                end
                LUT_PREP: begin
                    cdf <= cdf_next;
                    if (denominator == 0) begin
                        // A uniform frame keeps its original gray level.
                        equalize_lut[bin_index] <= bin_index;
                        state <= LUT_NEXT;
                    end else if (cdf_next <= cdf_min) begin
                        equalize_lut[bin_index] <= 8'd0;
                        state <= LUT_NEXT;
                    end else if (rounded_numerator >= (denominator_extended << 8)) begin
                        equalize_lut[bin_index] <= 8'd255;
                        state <= LUT_NEXT;
                    end else begin
                        remainder <= rounded_numerator;
                        quotient <= 8'd0;
                        division_bit <= 3'd7;
                        state <= DIVIDE;
                    end
                end
                DIVIDE: begin
                    // Shared unsigned trial division, quotient bits 7 down to 0.
                    if (trial_fits)
                        remainder <= remainder - trial;
                    quotient <= quotient_next;
                    if (division_bit == 0) begin
                        equalize_lut[bin_index] <= quotient_next;
                        state <= LUT_NEXT;
                    end else
                        division_bit <= division_bit - 1'b1;
                end
                LUT_NEXT: begin
                    if (bin_index == 8'd255) begin
                        read_address <= {ADDR_BITS{1'b0}};
                        state <= OUTPUT_READ;
                    end else begin
                        bin_index <= bin_index + 1'b1;
                        state <= LUT_PREP;
                    end
                end
                OUTPUT_READ: state <= OUTPUT_LOOKUP;
                OUTPUT_LOOKUP: begin
                    out_gray <= equalize_lut[frame_pixel];
                    out_valid <= 1'b1;
                    state <= OUTPUT_SEND;
                end
                OUTPUT_SEND: begin
                    // A blocked pixel remains valid and unchanged until consumed.
                    if (out_valid && out_ready) begin
                        out_valid <= 1'b0;
                        if (read_address == FRAME_PIXELS-1) begin
                            busy <= 1'b0;
                            done <= 1'b1;
                            state <= IDLE;
                        end else begin
                            read_address <= read_address + 1'b1;
                            state <= OUTPUT_READ;
                        end
                    end
                end
                default: begin
                    state <= IDLE;
                    busy <= 1'b0;
                    out_valid <= 1'b0;
                end
            endcase
        end
    end
endmodule
