# JMH build setup

Pin one JMH version across core, annotation processing, and build plugins. Check
the current version in the official OpenJDK JMH project rather than copying a
floating “latest” value.

## Maven shape

Keep `jmh-core` on the executable runtime classpath. Configure
`jmh-generator-annprocess` as an annotation processor; do not mark `jmh-core`
`provided` in a shaded standalone benchmark JAR.

```xml
<dependencies>
  <dependency>
    <groupId>org.openjdk.jmh</groupId>
    <artifactId>jmh-core</artifactId>
    <version>${jmh.version}</version>
  </dependency>
</dependencies>

<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-compiler-plugin</artifactId>
  <configuration>
    <annotationProcessorPaths>
      <path>
        <groupId>org.openjdk.jmh</groupId>
        <artifactId>jmh-generator-annprocess</artifactId>
        <version>${jmh.version}</version>
      </path>
    </annotationProcessorPaths>
  </configuration>
</plugin>
```

Build an executable shaded JAR whose main class is `org.openjdk.jmh.Main`, and
merge service resources as required by the chosen shade configuration. Verify:

```bash
java -jar target/benchmarks.jar -l
java -jar target/benchmarks.jar -h
```

The official JMH Maven archetype is a safer starting point than reconstructing
the full shade configuration from memory.

## Gradle shape

Use a pinned, maintained JMH Gradle plugin or configure both dependencies:

```groovy
dependencies {
    implementation "org.openjdk.jmh:jmh-core:${jmhVersion}"
    annotationProcessor "org.openjdk.jmh:jmh-generator-annprocess:${jmhVersion}"
}
```

Ensure the runnable benchmark task/JAR includes `jmh-core`, generated benchmark
classes/resources, project classes, and runtime dependencies. Run the list/help
checks above against the actual artifact. Do not treat successful Java
compilation as proof that annotation processing or packaging worked.
