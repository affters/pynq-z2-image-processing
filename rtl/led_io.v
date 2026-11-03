// PYNQ-Z2 first PL experiment: two switches and two buttons drive four LEDs.
// No clock, processor, SD card, or operating system is required.
module led_io (
    input  wire [1:0] sw,
    input  wire [1:0] btn,
    output wire [3:0] led
);
    assign led = {btn, sw};
endmodule
