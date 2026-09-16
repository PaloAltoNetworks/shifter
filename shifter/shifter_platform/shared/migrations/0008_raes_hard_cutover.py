from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shared", "0007_capacity_notification_and_audit_choices")]

    operations = [
        migrations.RenameModel(old_name="AcesOperationRecord", new_name="RaesOperationRecord"),
        migrations.AlterModelTable(name="raesoperationrecord", table="shared_raes_operation_record"),
        migrations.RenameIndex(
            model_name="raesoperationrecord",
            old_name="acesop_req_kind_src_idx",
            new_name="raesop_req_kind_src_idx",
        ),
        migrations.RenameIndex(
            model_name="raesoperationrecord",
            old_name="acesop_op_kind_idx",
            new_name="raesop_op_kind_idx",
        ),
        migrations.RenameIndex(
            model_name="raesoperationrecord",
            old_name="acesop_retention_idx",
            new_name="raesop_retention_idx",
        ),
        migrations.RemoveConstraint(
            model_name="raesoperationrecord",
            name="uniq_acesop_idempotency",
        ),
        migrations.AddConstraint(
            model_name="raesoperationrecord",
            constraint=models.UniqueConstraint(
                fields=(
                    "request_id",
                    "record_kind",
                    "contract_version",
                    "contract_profile",
                    "idempotency_key",
                ),
                name="uniq_raesop_idempotency",
            ),
        ),
        migrations.AlterField(
            model_name="raesoperationrecord",
            name="contract_kind",
            field=models.CharField(
                choices=[("raes", "RAES")],
                default="raes",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="raesoperationrecord",
            name="payload",
            field=models.JSONField(
                default=dict,
                help_text="Validated canonical RAES payload or bounded reference payload",
            ),
        ),
        migrations.AlterField(
            model_name="raesoperationrecord",
            name="owner",
            field=models.CharField(
                choices=[
                    ("shared", "Shared RAES boundary"),
                    ("engine", "Engine service"),
                    ("provisioner", "Provisioner"),
                    ("cms", "CMS service"),
                ],
                db_index=True,
                default="shared",
                max_length=32,
            ),
        ),
        migrations.RenameModel(
            old_name="AcesParticipantRuntimeRecord",
            new_name="RaesParticipantRuntimeRecord",
        ),
        migrations.AlterModelTable(
            name="raesparticipantruntimerecord",
            table="shared_raes_participant_runtime_record",
        ),
        migrations.RenameIndex(
            model_name="raesparticipantruntimerecord",
            old_name="acespr_req_kind_src_idx",
            new_name="raespr_req_kind_src_idx",
        ),
        migrations.RenameIndex(
            model_name="raesparticipantruntimerecord",
            old_name="acespr_ref_kind_idx",
            new_name="raespr_ref_kind_idx",
        ),
        migrations.RenameIndex(
            model_name="raesparticipantruntimerecord",
            old_name="acespr_retention_idx",
            new_name="raespr_retention_idx",
        ),
        migrations.RemoveConstraint(
            model_name="raesparticipantruntimerecord",
            name="uniq_acespr_idempotency",
        ),
        migrations.AddConstraint(
            model_name="raesparticipantruntimerecord",
            constraint=models.UniqueConstraint(
                fields=(
                    "request_id",
                    "participant_ref",
                    "record_kind",
                    "participant_runtime_profile",
                    "contract_version",
                    "idempotency_key",
                ),
                name="uniq_raespr_idempotency",
            ),
        ),
        migrations.AlterField(
            model_name="raesparticipantruntimerecord",
            name="contract_kind",
            field=models.CharField(
                choices=[("raes", "RAES")],
                default="raes",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="raesparticipantruntimerecord",
            name="payload",
            field=models.JSONField(
                default=dict,
                help_text="Validated canonical RAES participant-runtime payload or bounded reference payload",
            ),
        ),
        migrations.AlterField(
            model_name="raesparticipantruntimerecord",
            name="owner",
            field=models.CharField(
                choices=[
                    ("shared", "Shared RAES boundary"),
                    ("engine", "Engine service"),
                    ("provisioner", "Provisioner"),
                    ("cms", "CMS service"),
                    ("ctf", "CTF service"),
                ],
                db_index=True,
                default="shared",
                max_length=32,
            ),
        ),
    ]
