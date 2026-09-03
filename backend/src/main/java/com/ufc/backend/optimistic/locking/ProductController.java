package com.ufc.backend.optimistic.locking;



import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/products")
@RequiredArgsConstructor
public class ProductController {
    private final ProductService svc;

    // Not-found, sold-out and optimistic-locking conflicts are all handled
    // centrally by GlobalExceptionHandler — nothing to catch here.
    @PostMapping("/{id}/buy")
    public ResponseEntity<String> buy(@PathVariable Long id) {
        svc.buyOneOptimisticRepo(id);
        return ResponseEntity.ok("Purchase successful");
    }
}
