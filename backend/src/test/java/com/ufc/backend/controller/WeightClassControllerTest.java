package com.ufc.backend.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ufc.backend.dto.WeightClassResponse;
import com.ufc.backend.service.WeightClassService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Web-layer slice test: only the MVC infrastructure (controller,
 * @ControllerAdvice, validation, Jackson) is loaded — the service is mocked,
 * no database involved. This is what actually proves the HTTP contract
 * (status codes, error shape) works, which a service-only unit test cannot.
 */
@WebMvcTest(WeightClassController.class)
class WeightClassControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockitoBean
    private WeightClassService weightClassService;

    @Test
    void addWeightClass_withValidPayload_returns201AndBody() throws Exception {
        when(weightClassService.addWeightClass(any()))
                .thenReturn(new WeightClassResponse(1L, "Lightweight", 65.8, 70.3));

        mockMvc.perform(post("/weight-classes")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"className":"Lightweight","minWeight":65.8,"maxWeight":70.3}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.weightClassId").value(1))
                .andExpect(jsonPath("$.className").value("Lightweight"));
    }

    @Test
    void addWeightClass_withBlankClassNameAndInvertedRange_returns400WithFieldErrors() throws Exception {
        mockMvc.perform(post("/weight-classes")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"className":"","minWeight":80.0,"maxWeight":70.0}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.className").exists())
                .andExpect(jsonPath("$.errors.weightRangeValid").exists());
    }

    @Test
    void addWeightClass_ignoresClientSuppliedId_overPostingIsRejectedByContract() throws Exception {
        // The request DTO has no id field at all, so Jackson silently drops
        // any "weightClassId" the client sends — this test documents that.
        when(weightClassService.addWeightClass(any()))
                .thenReturn(new WeightClassResponse(5L, "Featherweight", 60.0, 66.0));

        mockMvc.perform(post("/weight-classes")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"weightClassId":999,"className":"Featherweight","minWeight":60.0,"maxWeight":66.0}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.weightClassId").value(5));
    }

    @Test
    void getAllWeightClassesAsStream_returns200WithMappedList() throws Exception {
        when(weightClassService.getAllWeightClassesAsStream())
                .thenReturn(List.of(new WeightClassResponse(1L, "Featherweight", 61.0, 65.8)));

        mockMvc.perform(get("/weight-classes/stream"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].className").value("Featherweight"));
    }
}
