package com.ticketing.inventory.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.GenericFilterBean;

import java.io.IOException;
import java.util.UUID;

// Registered automatically by Spring Boot as a servlet Filter just by
// being a bean (no FilterRegistrationBean needed). Every log line for the
// life of one request carries the same correlationId — the
// %X{correlationId:-none} slot in application.yml's logging.pattern that
// was left visibly unfilled since Day 1 finally gets a value here.
//
// Read-if-present, generate-if-not: a caller (or an upstream
// gateway/service, once one exists) can pass its own correlation id
// through to trace a request across service boundaries; a direct client
// hitting this service alone still gets one.
@Component
public class CorrelationIdFilter extends GenericFilterBean {

    public static final String HEADER_NAME = "X-Correlation-Id";
    public static final String MDC_KEY = "correlationId";

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest httpRequest = (HttpServletRequest) request;
        HttpServletResponse httpResponse = (HttpServletResponse) response;

        String correlationId = httpRequest.getHeader(HEADER_NAME);
        if (correlationId == null || correlationId.isBlank()) {
            correlationId = UUID.randomUUID().toString();
        }

        httpResponse.setHeader(HEADER_NAME, correlationId);
        MDC.put(MDC_KEY, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            // Tomcat reuses worker threads across requests — leaving this
            // in MDC would leak one request's correlation id into the
            // next request that happens to land on the same thread.
            MDC.remove(MDC_KEY);
        }
    }
}
