	.syntax unified
	.arm
	.global _start
	.type _start, %function

_start:
	ldr r0, [sp]
	add r1, sp, #4
	add r2, r1, r0, lsl #2
	add r2, r2, #4
	bl main
	mov r7, #1
	svc #0
