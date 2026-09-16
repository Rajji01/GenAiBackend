FROM eclipse-temurin:17-jdk AS build
WORKDIR /app

# Dependencies first, code second — same reasoning as narration-enrichment's
# Dockerfile: an ordinary code change should never re-trigger a full
# dependency download, only a pom.xml change should.
COPY mvnw .
COPY .mvn .mvn
COPY pom.xml .
RUN chmod +x mvnw && ./mvnw dependency:go-offline -B

COPY src ./src
RUN ./mvnw package -DskipTests -B

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY --from=build /app/target/inventory-service-*.jar app.jar

EXPOSE 8081
ENTRYPOINT ["java", "-jar", "app.jar"]
