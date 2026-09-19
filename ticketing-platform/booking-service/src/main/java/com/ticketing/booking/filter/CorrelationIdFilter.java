package com.ticketing.booking.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

// Copied verbatim from inventory-service — same reasoning as
// GlobalExceptionHandler: duplication over shared-lib coupling. When Day 3
// wires the inventory client, this same header will get forwarded on the
// outgoing REST call so both services log with the same correlation id
// (roadmap §6 Day 3).
@Component
@Order(1)
public class CorrelationIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Correlation-Id";
    public static final String MDC_KEY = "correlationId";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String incoming = request.getHeader(HEADER);
        String correlationId = (incoming == null || incoming.isBlank()) ? UUID.randomUUID().toString() : incoming;
        MDC.put(MDC_KEY, correlationId);
        response.setHeader(HEADER, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            // Tomcat reuses worker threads across requests — leaving this set
            // would leak one request's id into the next. Same bug the
            // inventory-service filter fixes; same fix.
            MDC.remove(MDC_KEY);
        }
    }
}
