.intel_syntax noprefix
.text
.globl _invoke_adjust
_invoke_adjust:
 push ebp
 mov ebp,esp
 push ebx
 push esi
 push edi
 mov ebx,0x11111111
 mov esi,0x22222222
 mov edi,0x33333333
 push 0x2468ace0
 push 0x13579bdf
 push dword ptr [ebp+32]
 push dword ptr [ebp+28]
 push dword ptr [ebp+24]
 push dword ptr [ebp+20]
 push dword ptr [ebp+16]
 push dword ptr [ebp+12]
 mov ecx,[ebp+36]
 mov [ecx+12],esp
 mov [ecx+20],ebp
 call dword ptr [ebp+8]
 mov ecx,[ebp+36]
 mov [ecx],ebx
 mov [ecx+4],esi
 mov [ecx+8],edi
 mov [ecx+16],esp
 mov [ecx+24],ebp
 mov [ecx+28],eax
 mov edx,[esp+24]
 mov [ecx+32],edx
 mov edx,[esp+28]
 mov [ecx+36],edx
 lea esp,[ebp-12]
 pop edi
 pop esi
 pop ebx
 leave
 ret
