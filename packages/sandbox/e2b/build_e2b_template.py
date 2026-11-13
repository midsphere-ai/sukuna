from dotenv import load_dotenv

from e2b import Template, default_build_logger

load_dotenv()

template = Template(file_context_path=".").from_dockerfile("e2b/Dockerfile")
# Build
Template.build(
    template,
    alias="exo-native-agent-sandbox",
    cpu_count=4,
    memory_mb=6192,
    on_build_logs=default_build_logger(),
)
