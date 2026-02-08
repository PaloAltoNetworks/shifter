"""Experiment manager admin configuration."""

from django.contrib import admin

from experiments.models import (
    Experiment,
    ExperimentArtifact,
    ExperimentRun,
    ExperimentScript,
    RunArtifact,
    ScriptAsset,
)


@admin.register(ScriptAsset)
class ScriptAssetAdmin(admin.ModelAdmin):
    list_display = ["name", "original_filename", "user", "file_size_bytes", "created_at", "deleted_at"]
    list_filter = ["created_at"]
    search_fields = ["name", "original_filename"]
    raw_id_fields = ["user"]
    readonly_fields = ["created_at", "s3_key", "sha256_hash"]


class ExperimentScriptInline(admin.TabularInline):
    model = ExperimentScript
    extra = 0
    raw_id_fields = ["script"]
    readonly_fields = ["execution_order"]


class ExperimentRunInline(admin.TabularInline):
    model = ExperimentRun
    extra = 0
    readonly_fields = ["uuid", "status", "started_at", "completed_at", "request_id"]
    fields = ["run_number", "uuid", "status", "started_at", "completed_at", "request_id"]


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "scenario_id", "status", "total_runs", "max_parallel_runs", "created_at"]
    list_filter = ["status", "scenario_id", "created_at"]
    search_fields = ["name", "uuid"]
    raw_id_fields = ["user", "agent"]
    readonly_fields = ["uuid", "created_at", "updated_at", "started_at", "completed_at"]
    inlines = [ExperimentScriptInline, ExperimentRunInline]


@admin.register(ExperimentScript)
class ExperimentScriptAdmin(admin.ModelAdmin):
    list_display = ["experiment", "instance_name", "script_type", "execution_order"]
    list_filter = ["script_type"]
    raw_id_fields = ["experiment", "script"]


@admin.register(ExperimentRun)
class ExperimentRunAdmin(admin.ModelAdmin):
    list_display = ["experiment", "run_number", "status", "started_at", "completed_at"]
    list_filter = ["status"]
    raw_id_fields = ["experiment"]
    readonly_fields = ["uuid", "started_at", "completed_at", "request_id"]


@admin.register(RunArtifact)
class RunArtifactAdmin(admin.ModelAdmin):
    list_display = ["run", "instance_name", "artifact_type", "file_size_bytes", "created_at"]
    list_filter = ["artifact_type"]
    raw_id_fields = ["run"]
    readonly_fields = ["created_at", "s3_key"]


@admin.register(ExperimentArtifact)
class ExperimentArtifactAdmin(admin.ModelAdmin):
    list_display = ["experiment", "file_size_bytes", "created_at"]
    raw_id_fields = ["experiment"]
    readonly_fields = ["created_at", "s3_key"]
