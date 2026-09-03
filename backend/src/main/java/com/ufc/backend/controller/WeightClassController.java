package com.ufc.backend.controller;


import com.ufc.backend.dto.WeightClassProjection;
import com.ufc.backend.dto.WeightClassRequest;
import com.ufc.backend.dto.WeightClassResponse;
import com.ufc.backend.service.WeightClassService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/weight-classes")
@RequiredArgsConstructor
public class WeightClassController {

    private final WeightClassService weightClassService;

    // ✅ GET /weight-classes → Get all UFC weight classes with Pagination and Sorting
    @GetMapping
    public ResponseEntity<Page<WeightClassProjection>> getWeightClasses(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(defaultValue = "className") String sortBy,
            @RequestParam(defaultValue = "asc") String direction) {

        Pageable pageable = PageRequest.of(page, size, Sort.by(
                direction.equalsIgnoreCase("asc") ? Sort.Direction.ASC : Sort.Direction.DESC, sortBy));

        return ResponseEntity.ok(weightClassService.getWeightClasses(pageable));
    }

    // ✅ GET /weight-classes/stream → Get all UFC weight classes as a Stream (Efficient for Large Data)
    @GetMapping("/stream")
    public ResponseEntity<List<WeightClassResponse>> getAllWeightClassesAsStream() {
        return ResponseEntity.ok(weightClassService.getAllWeightClassesAsStream());
    }

    // ✅ POST /weight-classes → Add a new weight class (Admin Only)
    @PostMapping
    public ResponseEntity<WeightClassResponse> addWeightClass(@Valid @RequestBody WeightClassRequest request) {
        WeightClassResponse created = weightClassService.addWeightClass(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }
}
