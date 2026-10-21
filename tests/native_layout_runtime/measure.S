.intel_syntax noprefix
.text
.globl _measure_stub
_measure_stub:
 push ebp
 mov ebp,esp
 push dword ptr [ebp+12]
 push dword ptr [ebp+8]
 push edx
 push ecx
 call _fake_measure
 add esp,16
 pop ebp
 ret
