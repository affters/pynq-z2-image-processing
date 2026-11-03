/* Freestanding UART -> ARM -> DDR/DMA/PL -> UART image protocol.
 * UART0 clock/pins and caches use the matching PS/startup loader.
 * No libc, interrupts, SD, Flash, or allocation.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define UART_BASE 0xE0000000u
#define UART_ISR 0x14u
#define UART_SR 0x2Cu
#define UART_FIFO 0x30u
#define RXEMPTY 0x02u
#define TXFULL 0x10u
#define RX_ERRORS 0xE0u
#define FRAME_POLL_BUDGET 50000000u
#ifndef IMAGE_WIDTH
#define IMAGE_WIDTH 128u
#endif
#ifndef IMAGE_HEIGHT
#define IMAGE_HEIGHT 96u
#endif
#if !((IMAGE_WIDTH == 128 && IMAGE_HEIGHT == 96) || \
      (IMAGE_WIDTH == 256 && IMAGE_HEIGHT == 192))
#error Unsupported image resolution profile
#endif
#define PIXELS (IMAGE_WIDTH * IMAGE_HEIGHT)
#define RGB_BYTES (PIXELS * 3u)
#define INNER_PIXELS ((IMAGE_WIDTH - 2u) * (IMAGE_HEIGHT - 2u))
#define DMA_BASE 0x40400000u
#define GPIO_BASE 0x41200000u
#define INPUT_BASE 0x10000000u
#define OUTPUT_BASE 0x11000000u
#define DMA_POLL_BUDGET 5000000u

#ifndef UART_BAUD
#define UART_BAUD 115200
#endif
/* Matching HWH: UART_REF = 100 MHz, baud = ref / (CD * (BDIV + 1)). */
#if UART_BAUD == 115200
#define UART_CD 124u
#define UART_BDIV 6u
#elif UART_BAUD == 1000000
#define UART_CD 4u
#define UART_BDIV 24u
#elif UART_BAUD == 2000000
#define UART_CD 2u
#define UART_BDIV 24u
#else
#error Unsupported UART_BAUD
#endif

volatile u32 fw_request_count;
volatile u32 fw_last_status;
volatile u32 fw_ready;
volatile u32 fw_uart_init_error;
volatile u32 fw_processed_frames;
volatile u32 fw_dma_tx_status;
volatile u32 fw_dma_rx_status;
volatile u32 fw_dma_poisoned;
volatile u32 fw_dma_stages[9];
volatile u32 fw_sctlr;
volatile u32 fw_l2_control;
volatile u32 fw_dma_source_at_submit;
volatile u32 fw_dma_destination_at_submit;
static u8 rgb_body[RGB_BYTES];
static u8 gray_body[PIXELS];

static const u8 request_magic[8] = {'P','Y','N','Q','I','M','G','1'};
static const u8 response_magic[8] = {'P','Y','N','Q','R','E','S','1'};
#if IMAGE_WIDTH == 128 && IMAGE_HEIGHT == 96
static const u8 info_body[] = "pynq_uart_image_v1";
#else
static const u8 info_body[] = "pynq_uart_image_256x192_v1";
#endif

static u32 reg_read(u32 offset) { return *(volatile u32 *)(UART_BASE + offset); }
static void reg_write(u32 offset, u32 value) { *(volatile u32 *)(UART_BASE + offset) = value; }

static int uart_initialize(void)
{
    reg_write(0x00u,0x28u); /* Disable TX/RX before changing the divisors. */
    reg_write(0x04u,0x20u); /* Normal mode, 8N1, undivided UART_REF. */
    reg_write(0x18u,UART_CD);
    reg_write(0x34u,UART_BDIV);
    reg_write(0x00u,0x03u); /* Reset both FIFOs; mirrors Xilinx uartps driver. */
    __asm__ volatile("dsb sy" ::: "memory");
    for (u32 i=0; i<FRAME_POLL_BUDGET; ++i) {
        if (!(reg_read(0x00u)&3u)) {
            reg_write(0x00u,0x14u); /* Enable TX/RX. */
            reg_write(UART_ISR,RX_ERRORS);
            __asm__ volatile("dsb sy" ::: "memory");
            return 1;
        }
    }
    fw_uart_init_error=1u;
    return 0;
}

/* A single shared budget bounds all waits in one started header/body/response. */
static int uart_get(u8 *value, u32 *budget)
{
    for (;;) {
        u32 errors = reg_read(UART_ISR) & RX_ERRORS;
        if (errors) { reg_write(UART_ISR, errors); return 0; }
        if (!(reg_read(UART_SR) & RXEMPTY)) {
            *value = (u8)reg_read(UART_FIFO);
            return 1;
        }
        if (*budget == 0u) return 0;
        --*budget;
    }
}

static int uart_put(u8 value, u32 *budget)
{
    while (reg_read(UART_SR) & TXFULL) {
        if (*budget == 0u) return 0;
        --*budget;
    }
    reg_write(UART_FIFO, value);
    return 1;
}

static u32 get32(const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}
static u16 get16(const u8 *p) { return (u16)((u32)p[0] | ((u32)p[1] << 8)); }
static void put32(u8 *p, u32 v)
{
    p[0]=(u8)v; p[1]=(u8)(v>>8); p[2]=(u8)(v>>16); p[3]=(u8)(v>>24);
}
static void put16(u8 *p, u16 v) { p[0]=(u8)v; p[1]=(u8)(v>>8); }

static u32 crc32_bytes(const u8 *p, u32 count)
{
    u32 crc=0xFFFFFFFFu;
    for (u32 i=0; i<count; ++i) {
        crc ^= p[i];
        for (u32 bit=0; bit<8u; ++bit)
            crc=(crc>>1) ^ ((0u-(crc&1u)) & 0xEDB88320u);
    }
    return crc ^ 0xFFFFFFFFu;
}

static void respond(u32 sequence, u32 status, u16 width, u16 height,
                    const u8 *body, u32 length, u32 core_status)
{
    u8 h[32];
    u32 budget=FRAME_POLL_BUDGET;
    for (u32 i=0; i<8u; ++i) h[i]=response_magic[i];
    put32(h+8, sequence); put32(h+12, status);
    put16(h+16, width); put16(h+18, height);
    put32(h+20, length); put32(h+24, crc32_bytes(body,length));
    put32(h+28,core_status);
    fw_last_status=status;
    for (u32 i=0; i<32u; ++i) if (!uart_put(h[i],&budget)) return;
    for (u32 i=0; i<length; ++i) if (!uart_put(body[i],&budget)) return;
}

static void barrier(void) { __asm__ volatile("dsb sy" ::: "memory"); }
static u32 mmio_read(u32 address) { return *(volatile u32 *)address; }
static void mmio_write(u32 address, u32 value) {
    *(volatile u32 *)address=value;
    barrier();
}

static void core_reset(u32 mode)
{
    mmio_write(GPIO_BASE,mode|0x200u);
    barrier();
    for (u32 i=0; i<1000u; ++i) __asm__ volatile("nop");
    mmio_write(GPIO_BASE,mode);
    barrier();
}

static int dma_reset(void)
{
    mmio_write(DMA_BASE,4u);
    barrier();
    for (u32 count=0; count<DMA_POLL_BUDGET; ++count)
        if (!(mmio_read(DMA_BASE)&4u)) return 1;
    fw_dma_poisoned=1u;
    return 0;
}

static u32 process_frame(u32 mode,u16 *out_width,u16 *out_height,u32 *core_status)
{
    if (fw_dma_poisoned) return 4u;
    u32 output_pixels=(mode==0u || mode==4u) ? PIXELS : INNER_PIXELS;
    volatile u32 *input=(volatile u32 *)INPUT_BASE;
    volatile u32 *output=(volatile u32 *)OUTPUT_BASE;
    *out_width=(mode==0u || mode==4u) ? IMAGE_WIDTH : IMAGE_WIDTH-2u;
    *out_height=(mode==0u || mode==4u) ? IMAGE_HEIGHT : IMAGE_HEIGHT-2u;
    *core_status=0u;
    for (u32 i=0; i<PIXELS; ++i)
        input[i]=((u32)rgb_body[i*3u]<<16)|((u32)rgb_body[i*3u+1u]<<8)|rgb_body[i*3u+2u];
    for (u32 i=0; i<output_pixels; ++i) output[i]=0xDEADBEEFu;
    barrier();
    mmio_write(GPIO_BASE+4u,0u);
    mmio_write(GPIO_BASE+12u,0xFFFFFFFFu);
    core_reset(mode);
    fw_dma_stages[0]=mmio_read(GPIO_BASE+8u);
    if (!dma_reset()) return 4u;
    fw_dma_stages[1]=mmio_read(DMA_BASE);
    fw_dma_stages[2]=mmio_read(DMA_BASE+0x30u);
    mmio_write(DMA_BASE,1u);
    mmio_write(DMA_BASE+0x30u,1u);
    fw_dma_stages[3]=mmio_read(GPIO_BASE+8u);
    fw_dma_stages[4]=mmio_read(DMA_BASE+4u);
    fw_dma_stages[5]=mmio_read(DMA_BASE+0x34u);
    mmio_write(GPIO_BASE,mode|0x100u);
    barrier();
    mmio_write(GPIO_BASE,mode);
    fw_dma_stages[6]=mmio_read(GPIO_BASE+8u);
    /* Arm receive before send. Both buffers and AXIS words are 32 bits. */
    mmio_write(DMA_BASE+0x48u,OUTPUT_BASE);
    mmio_write(DMA_BASE+0x4Cu,0u);
    fw_dma_destination_at_submit=mmio_read(DMA_BASE+0x48u);
    if (fw_dma_destination_at_submit!=OUTPUT_BASE) {
        if (dma_reset()) core_reset(mode);
        return 8u;
    }
    mmio_write(DMA_BASE+0x58u,output_pixels*4u);
    barrier();
    fw_dma_stages[7]=mmio_read(GPIO_BASE+8u);
    mmio_write(DMA_BASE+0x18u,INPUT_BASE);
    mmio_write(DMA_BASE+0x1Cu,0u);
    fw_dma_source_at_submit=mmio_read(DMA_BASE+0x18u);
    if (fw_dma_source_at_submit!=INPUT_BASE) {
        if (dma_reset()) core_reset(mode);
        return 8u;
    }
    mmio_write(DMA_BASE+0x28u,PIXELS*4u);
    barrier();
    fw_dma_stages[8]=mmio_read(GPIO_BASE+8u);
    u32 completed=0u;
    for (u32 count=0; count<DMA_POLL_BUDGET; ++count) {
        *core_status=mmio_read(GPIO_BASE+8u);
        fw_dma_tx_status=mmio_read(DMA_BASE+4u);
        fw_dma_rx_status=mmio_read(DMA_BASE+0x34u);
        if ((*core_status&4u) || ((fw_dma_tx_status|fw_dma_rx_status)&0x70u)) {
            if (dma_reset()) core_reset(mode);
            return 4u;
        }
        if ((*core_status&3u)==2u && (fw_dma_tx_status&2u) && (fw_dma_rx_status&2u)) {
            completed=1u;
            break;
        }
    }
    if (!completed) {
        if (dma_reset()) core_reset(mode);
        return 5u;
    }
    barrier();
    if (mmio_read(DMA_BASE+0x58u)!=output_pixels*4u) return 6u;
    for (u32 i=0; i<output_pixels; ++i) {
        u32 value=output[i];
        if (value&0xFFFFFF00u) return 7u;
        gray_body[i]=(u8)value;
    }
    ++fw_processed_frames;
    return 0u;
}

int main(void)
{
    u8 h[32];
    u32 matched=0;
    if (!uart_initialize()) for (;;) __asm__ volatile("wfe");
    fw_ready=0x55415231u;
    __asm__ volatile("mrc p15, 0, %0, c1, c0, 0" : "=r" (fw_sctlr));
    fw_l2_control=mmio_read(0xF8F02100u);
    reg_write(UART_ISR, RX_ERRORS);
    for (;;) {
        /* Idle is intentionally unbounded. Partial magic has no memory growth. */
        u8 c;
        u32 idle_budget=FRAME_POLL_BUDGET;
        if (!uart_get(&c,&idle_budget)) { matched=0; continue; }
        if (c==request_magic[matched]) ++matched;
        else matched=(c==request_magic[0]) ? 1u : 0u;
        if (matched!=8u) continue;
        matched=0;
        for (u32 i=0; i<8u; ++i) h[i]=request_magic[i];
        u32 budget=FRAME_POLL_BUDGET;
        u32 i;
        for (i=8; i<32u; ++i) if (!uart_get(h+i,&budget)) break;
        if (i!=32u) continue;
        u32 sequence=get32(h+8), command=get32(h+12), mode=get32(h+16);
        u16 width=get16(h+20), height=get16(h+22);
        u32 length=get32(h+24), crc=get32(h+28);
        ++fw_request_count;
        if (command==1u && mode==0u && length==0u && crc==0u &&
            ((width==0u && height==0u) || (width==IMAGE_WIDTH && height==IMAGE_HEIGHT))) {
            respond(sequence,0u,IMAGE_WIDTH,IMAGE_HEIGHT,info_body,(u32)sizeof(info_body)-1u,0u);
        } else if (command==2u && mode<5u && width==IMAGE_WIDTH && height==IMAGE_HEIGHT && length==RGB_BYTES) {
            u32 receive_budget=FRAME_POLL_BUDGET;
            for (i=0; i<RGB_BYTES; ++i) if (!uart_get(rgb_body+i,&receive_budget)) break;
            if (i!=RGB_BYTES) {
                respond(sequence,2u,0u,0u,(const u8 *)0,0u,0u);
                continue;
            }
            if (crc32_bytes(rgb_body,RGB_BYTES)!=crc) {
                respond(sequence,3u,0u,0u,(const u8 *)0,0u,0u);
                continue;
            }
            u16 out_width=0u,out_height=0u;
            u32 core_status=0u;
            u32 status=process_frame(mode,&out_width,&out_height,&core_status);
            if (status) respond(sequence,status,0u,0u,(const u8 *)0,0u,core_status);
            else respond(sequence,0u,out_width,out_height,gray_body,(u32)out_width*out_height,core_status);
        } else {
            respond(sequence,12u,0u,0u,(const u8 *)0,0u,0u);
        }
    }
}
