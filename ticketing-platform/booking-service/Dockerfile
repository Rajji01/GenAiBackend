FROM eclipse-temurin:17-jdk AS build
WORKDIR /app

# Same layering discipline as inventory-service's Dockerfile: dependencies
# resolved BEFORE source code is copied in, so ordinary code changes reuse
# the cached deps layer instead of re-downloading the world on every rebuild.
COPY mvnw .
COPY .mvn .mvn
COPY pom.xml .
RUN chmod +x mvnw && ./mvnw dependency:go-offline -B

COPY src ./src
RUN ./mvnw package -DskipTests -B

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY --from=build /app/target/booking-service-*.jar app.jar

# 8082, not 8081 — inventory holds 8081. Two services on one port would
# be an obvious collision, but only if they're on the same host. Inside
# the compose network each container has its own IP, so the ports COULD
# have matched — keeping them different is a courtesy for anyone running
# both against the host at once (dev laptop, port-forwarded to Postman).
EXPOSE 8082
ENTRYPOINT ["java", "-jar", "app.jar"]
