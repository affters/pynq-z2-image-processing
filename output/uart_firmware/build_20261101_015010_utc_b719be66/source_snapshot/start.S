.syntax unified
.arch armv7-a
.arm
.section .vectors,"ax",%progbits
.balign 32
.global _start
.type _start,%function
_start:
    b reset_entry
    b exception_stop
    b exception_stop
    b exception_stop
    b exception_stop
    b exception_stop
    b exception_stop
    b exception_stop
reset_entry:
    cpsid aif
    mrc p15, 0, r1, c1, c0, 0
    bic r1, r1, #5
    bic r1, r1, #0x1000
    bic r1, r1, #0x800
    dsb sy
    mcr p15, 0, r1, c1, c0, 0
    isb
    mov r0, #0
    mcr p15, 0, r0, c8, c7, 0
    mcr p15, 0, r0, c7, c5, 0
    mcr p15, 0, r0, c7, c5, 6
    ldr r1, =0xf8f02100
    str r0, [r1]
    dsb sy
    isb
    ldr r1, =_start
    mcr p15, 0, r1, c12, c0, 0
    isb
    ldr sp, =__stack_top
    ldr r1, =__bss_start
    ldr r2, =__bss_end
clear_bss:
    cmp r1, r2
    strlo r0, [r1], #4
    blo clear_bss
    bl main
exception_stop:
    b exception_stop
.size _start, .-_start
.ltorg
