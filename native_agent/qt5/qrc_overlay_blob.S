/* qrc_overlay.so built for the same target, carried inside the agent, which
   writes it next to itself for the display start script. */
	.section .rodata
	.global c300x_qrc_overlay_so
	.global c300x_qrc_overlay_so_end
	.balign 4
c300x_qrc_overlay_so:
	.incbin QRC_OVERLAY_SO
c300x_qrc_overlay_so_end:
	.section .note.GNU-stack,"",%progbits
