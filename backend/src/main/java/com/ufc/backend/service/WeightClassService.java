package com.ufc.backend.service;




import com.ufc.backend.dto.WeightClassProjection;
import com.ufc.backend.dto.WeightClassRequest;
import com.ufc.backend.dto.WeightClassResponse;
import com.ufc.backend.entities.WeightClass;
import com.ufc.backend.repository.WeightClassRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Service
@RequiredArgsConstructor
public class WeightClassService {

    private final WeightClassRepository weightClassRepository;

    // Fetch Weight Classes using Pagination, Sorting, and Projection
    public Page<WeightClassProjection> getWeightClasses(Pageable pageable) {
        return weightClassRepository.findAllProjectedBy(pageable);
    }

    // Fetch Weight Classes using Stream Processing
    @Transactional(readOnly = true)
    public List<WeightClassResponse> getAllWeightClassesAsStream() {
        try (Stream<WeightClass> weightClassStream = weightClassRepository.streamAllWeightClasses()) {
            return weightClassStream
                    .map(WeightClassResponse::from)
                    .collect(Collectors.toList());
        }
    }

    // Add a New Weight Class (Admin Only)
    @Transactional
    public WeightClassResponse addWeightClass(WeightClassRequest request) {
        WeightClass weightClass = WeightClass.builder()
                .className(request.className())
                .minWeight(request.minWeight())
                .maxWeight(request.maxWeight())
                .build();

        WeightClass saved = weightClassRepository.save(weightClass);
        return WeightClassResponse.from(saved);
    }
}
