ENTRY(_start)
PHDRS {
    code PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
}
SECTIONS {
    . = 0x00100000;
    .vectors : { KEEP(*(.vectors)) } :code
    .text : { *(.text*) } :code
    .rodata : { *(.rodata*) } :code
    . = ALIGN(64);
    .data : { *(.data*) } :data
    . = ALIGN(4);
    __bss_start = .;
    .bss (NOLOAD) : { *(.bss*) *(COMMON) . = ALIGN(4); } :data
    __bss_end = .;
    __stack_top = 0x001f0000;
    ASSERT(__bss_end <= 0x001e0000, "Firmware overlaps reserved stack region")
    /DISCARD/ : { *(.comment*) *(.note*) *(.ARM.exidx*) *(.ARM.extab*) }
}
