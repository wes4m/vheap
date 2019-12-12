#include <stdio.h>



int main() {
	
	void* ptr[10] = {0};

	// allocates of sie 0x20 tcahce bin
	for(int i = 0; i < 10; i++) {
		ptr[i] = malloc(16);
	}

	// frees until some go into fastbin
	for(int i = 0; i < 10; i++) {
		free(ptr[i]);
	}

	getchar(); // bp

}
