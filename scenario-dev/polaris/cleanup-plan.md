# Polaris CTF — Range Cleanup Plan

**Event:** BSides Ottawa — Polaris CTF
**Event UUID:** `fa1988b5-18fc-41d3-b3ff-ee97b0549546`
**Generated:** 2026-04-17T00:47:02.757324+00:00
**Trigger time:** 2026-04-18 00:00 EDT (2026-04-18 04:00 UTC) — event end
**Cleanup grace:** 24 h via `auto_cleanup` — ranges will auto-destroy at 2026-04-19 00:00 EDT if not manually triggered

## Policy

- **KEEP** the ranges of the 12 operators who completed Mission 4 — Lights Out.
  They earned access to the Bunker and we manually spliced their networks late
  in the event; they deserve time to finish what they started.
- **DESTROY** every other range attached to the event.

The keep list is derived from `ctf.models.Solves` join on the "Lights Out"
challenge in CTFd, as of the end of the original event window.

## Keep list — 12 operators (12 found)

| Participant UUID | Email | Range instance | Range status |
|---|---|---|---|
| `bb9777a4-b72c-420c-80f2-d5daf0492066` | meetup+1@bsidesottawa.ca | range_instance=28 | range_status=ready |
| `fb5195cb-1139-412b-9752-a2384a1ac04f` | meetup+7@bsidesottawa.ca | range_instance=115 | range_status=ready |
| `c60e521c-419d-40b4-bdfc-377198eec622` | meetup+17@bsidesottawa.ca | range_instance=47 | range_status=ready |
| `80d3d2cc-7692-4746-b561-64aa1ef49309` | meetup+22@bsidesottawa.ca | range_instance=52 | range_status=ready |
| `87a96d93-191f-49be-8112-df6229ea0f9b` | meetup+24@bsidesottawa.ca | range_instance=54 | range_status=ready |
| `5aa6dea6-7da1-486f-bafd-4616ba868913` | meetup+38@bsidesottawa.ca | range_instance=69 | range_status=ready |
| `3f821c04-3d7b-47bd-80b4-cd86118ba74a` | meetup+44@bsidesottawa.ca | range_instance=76 | range_status=ready |
| `4366c427-c028-4cb9-9558-344241e1cf3b` | meetup+82@bsidesottawa.ca | range_instance=118 | range_status=ready |
| `39510aa3-2729-4950-b7d7-009e4ea12901` | meetup+95@bsidesottawa.ca | range_instance=132 | range_status=ready |
| `51fe9a9e-fb03-4d78-8d6b-7edfa916f78e` | meetup+98@bsidesottawa.ca | range_instance=135 | range_status=ready |
| `79d4dcf4-2251-4b5e-a4a9-5745a0dfdd97` | meetup+106@bsidesottawa.ca | range_instance=36 | range_status=ready |
| `d3d6a055-1145-4846-a71f-10843143d6ed` | meetup+107@bsidesottawa.ca | range_instance=37 | range_status=ready |

## Destroy list — 99 ranges

Includes one admin/QA test account (`claude-test+qa@bsidesottawa.ca`) alongside
the other 98 participant ranges that never completed Lights Out.

| Participant UUID | Email | Range instance |
|---|---|---|
| `8bf6a841-d9d8-47b3-b7fd-01e83e89c01d` | meetup+2@bsidesottawa.ca | range_instance=60 |
| `2947553d-0512-403c-bf5b-1e10804d81dc` | meetup+3@bsidesottawa.ca | range_instance=71 |
| `1fe83b4a-aac4-4950-ac1e-b4530a02aa20` | meetup+4@bsidesottawa.ca | range_instance=82 |
| `eeb598ac-9e03-40aa-9530-0d0a48779fcf` | meetup+5@bsidesottawa.ca | range_instance=93 |
| `3e07f173-4c32-452a-b8ea-a95b4bd26777` | meetup+6@bsidesottawa.ca | range_instance=104 |
| `5bae11a5-7647-4ec6-bf0d-aee8a1fe5716` | meetup+8@bsidesottawa.ca | range_instance=126 |
| `c6d1c525-2643-41db-a795-3214b5297f3a` | meetup+9@bsidesottawa.ca | range_instance=137 |
| `32678cf0-2bee-42c6-ab2f-b784e59e1c02` | meetup+10@bsidesottawa.ca | range_instance=29 |
| `d71cb5e8-053f-4f38-b74d-d98706d20b3c` | meetup+11@bsidesottawa.ca | range_instance=40 |
| `cf732cb0-7ec8-4fe9-aa08-bafd104a18dc` | meetup+12@bsidesottawa.ca | range_instance=42 |
| `72086f48-fd2d-4155-8206-93f079463cf9` | meetup+13@bsidesottawa.ca | range_instance=43 |
| `9db691e4-1a11-490d-acc4-8a4ecfeaedbc` | meetup+14@bsidesottawa.ca | range_instance=44 |
| `7ff699e7-5ce3-40d8-8c70-8b1e6cb623cf` | meetup+15@bsidesottawa.ca | range_instance=45 |
| `ae307735-7d36-4d27-ae25-5ce7c2c1f1b8` | meetup+16@bsidesottawa.ca | range_instance=46 |
| `fe0a9ebe-bc1c-49b7-b5f0-57ec2c74c634` | meetup+18@bsidesottawa.ca | range_instance=48 |
| `4e126424-91d1-4938-9087-fa97504e3a47` | meetup+19@bsidesottawa.ca | range_instance=49 |
| `f2180402-0f5b-4930-8934-bd36018b7407` | meetup+20@bsidesottawa.ca | range_instance=50 |
| `ac281ca4-591e-48ff-b3a6-f00d3dc25f64` | meetup+21@bsidesottawa.ca | range_instance=51 |
| `fb197d5b-6c80-4e08-9a9e-c0fdf089291f` | meetup+23@bsidesottawa.ca | range_instance=53 |
| `82af8c3f-2621-445e-8a22-422b9fa3d03a` | meetup+25@bsidesottawa.ca | range_instance=55 |
| `d893e652-844e-40f4-aad1-4c843599d15c` | meetup+26@bsidesottawa.ca | range_instance=56 |
| `4ed67aa5-f350-471e-aeda-7f49930f642f` | meetup+27@bsidesottawa.ca | range_instance=57 |
| `b646ea1d-e940-4f8a-b9ea-2f032e5b39b2` | meetup+28@bsidesottawa.ca | range_instance=58 |
| `bbceaaaf-fd06-44ab-b9f5-3ed57962d31b` | meetup+29@bsidesottawa.ca | range_instance=59 |
| `f2906132-406a-4182-afaf-a3e62149b04d` | meetup+30@bsidesottawa.ca | range_instance=61 |
| `b06384bc-b6e7-4051-84d7-d288fdc56767` | meetup+31@bsidesottawa.ca | range_instance=62 |
| `7d8067e3-ee7c-4a02-a008-ab368b20a62e` | meetup+32@bsidesottawa.ca | range_instance=63 |
| `32eb24b6-ad96-43fc-a8d6-650da2306a20` | meetup+33@bsidesottawa.ca | range_instance=64 |
| `ce4cc261-db12-4391-9ad1-9f840f0a40b8` | meetup+34@bsidesottawa.ca | range_instance=65 |
| `02932367-c61c-4f9e-ab52-4078d080f4e6` | meetup+35@bsidesottawa.ca | range_instance=66 |
| `a3111373-58c1-43b2-87d8-bf1aa53ff089` | meetup+36@bsidesottawa.ca | range_instance=67 |
| `4b1b844a-1d92-4310-9f08-bdbe3433324e` | meetup+37@bsidesottawa.ca | range_instance=68 |
| `b0c71e97-fb99-4261-bceb-4c6c4ba85cb4` | meetup+39@bsidesottawa.ca | range_instance=70 |
| `13057dc2-5844-447f-804b-c392e9360ecc` | meetup+40@bsidesottawa.ca | range_instance=72 |
| `b323bb65-b349-4cb5-97d5-907a92181771` | meetup+41@bsidesottawa.ca | range_instance=73 |
| `d0e4708f-e61f-4af5-b7e1-8d296f657a6c` | meetup+42@bsidesottawa.ca | range_instance=74 |
| `d7fc8da9-a964-4d2e-bece-85cd91ff5828` | meetup+43@bsidesottawa.ca | range_instance=75 |
| `4a3e16cd-8490-42a6-8b96-24b3ce5e7551` | meetup+45@bsidesottawa.ca | range_instance=77 |
| `0c11d6f8-1b55-4aba-894b-bb31ee1fe17c` | meetup+46@bsidesottawa.ca | range_instance=78 |
| `0b26e0aa-ae47-4b98-9a8f-a900e2baf5a8` | meetup+47@bsidesottawa.ca | range_instance=79 |
| `8b71713e-a745-4408-845d-1a8c9e49977c` | meetup+48@bsidesottawa.ca | range_instance=80 |
| `a0048e6b-8ea2-4d5b-ab37-1baa9fb793ee` | meetup+49@bsidesottawa.ca | range_instance=81 |
| `396656bd-9db6-4589-9153-e518a83f7870` | meetup+50@bsidesottawa.ca | range_instance=83 |
| `38014669-236b-466b-b36a-59dacdf07d59` | meetup+51@bsidesottawa.ca | range_instance=84 |
| `2d4b2b5e-cd5c-409c-8632-d0651cee15db` | meetup+52@bsidesottawa.ca | range_instance=85 |
| `e6df99bb-493f-48b7-a5f5-003dd966741f` | meetup+53@bsidesottawa.ca | range_instance=86 |
| `e8c6a749-631b-4121-b4da-3f04ae9a4506` | meetup+54@bsidesottawa.ca | range_instance=87 |
| `6dd81786-ac30-4a9d-bde6-576b9bc1bb4b` | meetup+55@bsidesottawa.ca | range_instance=88 |
| `b06747e2-9c46-44fd-858e-054935e979cb` | meetup+56@bsidesottawa.ca | range_instance=89 |
| `a29a6755-6fa7-4ce9-b2c2-e863d8b01796` | meetup+57@bsidesottawa.ca | range_instance=90 |
| `0bffe004-1b4e-4846-a6db-2b41e6405f48` | meetup+58@bsidesottawa.ca | range_instance=91 |
| `19b2b760-4c07-4b67-92e0-e303fa20ebf2` | meetup+59@bsidesottawa.ca | range_instance=92 |
| `4d52e1b1-92e7-4b50-89bb-b0448108e370` | meetup+60@bsidesottawa.ca | range_instance=94 |
| `33a3902a-dba6-42a8-bf6d-ac2561e3e55e` | meetup+61@bsidesottawa.ca | range_instance=95 |
| `e1b0b07b-5614-4866-bbd5-00db006f2982` | meetup+62@bsidesottawa.ca | range_instance=96 |
| `db486371-b779-4791-9ae7-324fb2cb51bf` | meetup+63@bsidesottawa.ca | range_instance=97 |
| `2b8535ac-2b0e-484c-9656-0dd2aa1594f3` | meetup+64@bsidesottawa.ca | range_instance=98 |
| `f57ac07a-6d7c-4bcb-90ff-135981a849ca` | meetup+65@bsidesottawa.ca | range_instance=99 |
| `8299fe77-f6db-45e2-9ede-2485e2a55cd9` | meetup+66@bsidesottawa.ca | range_instance=100 |
| `a41a15d8-5ec9-40e4-a137-f7222fd61129` | meetup+67@bsidesottawa.ca | range_instance=101 |
| `e70be8a2-f386-4372-b7be-67f788f82c82` | meetup+68@bsidesottawa.ca | range_instance=102 |
| `0cc99eea-fc6b-4ff1-b76e-674314607a0a` | meetup+69@bsidesottawa.ca | range_instance=103 |
| `3c03c326-de8c-46c1-82ba-9418ea8e4c3f` | meetup+70@bsidesottawa.ca | range_instance=105 |
| `4dac8bf6-3424-4f3c-a56d-3136f0747560` | meetup+71@bsidesottawa.ca | range_instance=106 |
| `e83c72a0-bffc-4b7e-8a14-d7c5d7002645` | meetup+72@bsidesottawa.ca | range_instance=107 |
| `fe7ca02e-ae4c-4bee-b1c5-96cc9e0508f0` | meetup+73@bsidesottawa.ca | range_instance=108 |
| `6db875f3-30f9-41a2-8aa6-bf057eaa96a0` | meetup+74@bsidesottawa.ca | range_instance=109 |
| `ec09ddcf-b018-41ef-86a3-a83c3dbe4a27` | meetup+75@bsidesottawa.ca | range_instance=110 |
| `77665430-254a-47b1-ad1d-a0a133e1d886` | meetup+76@bsidesottawa.ca | range_instance=111 |
| `e428c27e-3cd1-423a-9342-fa51f46accd9` | meetup+77@bsidesottawa.ca | range_instance=112 |
| `75ea67c2-5e83-48e1-813f-57e314d960d8` | meetup+78@bsidesottawa.ca | range_instance=113 |
| `1cd8b3f2-2e78-483e-8733-c9eb7bfd0535` | meetup+79@bsidesottawa.ca | range_instance=114 |
| `0a25514e-b972-41f8-9069-65bed35fd65e` | meetup+80@bsidesottawa.ca | range_instance=116 |
| `c96da06f-8da8-42b4-8c0c-a495ab224227` | meetup+81@bsidesottawa.ca | range_instance=117 |
| `b58414d8-89d3-4400-83b4-429d7c20e3cb` | meetup+83@bsidesottawa.ca | range_instance=119 |
| `26f4e035-ebe9-4586-a387-2ac3397e6035` | meetup+84@bsidesottawa.ca | range_instance=120 |
| `b7611436-c45d-408c-bfa3-c824c21dd5db` | meetup+85@bsidesottawa.ca | range_instance=121 |
| `6d6a172a-8b07-4a18-8d91-3bbe31377cae` | meetup+86@bsidesottawa.ca | range_instance=122 |
| `61131597-f495-495e-8b04-dd3c4b929941` | meetup+87@bsidesottawa.ca | range_instance=123 |
| `4b82727d-a64a-472f-bc82-3ca163d200ef` | meetup+88@bsidesottawa.ca | range_instance=124 |
| `37e7cd30-d1a3-49d0-9e25-95d05d9d70f2` | meetup+89@bsidesottawa.ca | range_instance=125 |
| `5b377136-31d2-41b1-9f85-b6dea23f323a` | meetup+90@bsidesottawa.ca | range_instance=127 |
| `5d8f3d7f-ee53-460b-a212-2f1224b37d90` | meetup+91@bsidesottawa.ca | range_instance=128 |
| `18268d29-5798-4705-81ee-af082f580be5` | meetup+92@bsidesottawa.ca | range_instance=129 |
| `43dca469-9fd3-4a97-b8b6-f87a793e5f96` | meetup+93@bsidesottawa.ca | range_instance=130 |
| `1677987a-d5a1-46ad-a9f9-ee3d67d1497f` | meetup+94@bsidesottawa.ca | range_instance=131 |
| `999e27bd-e7af-4a1e-97be-7fad0f7bd76e` | meetup+96@bsidesottawa.ca | range_instance=133 |
| `bc4537ab-2ba7-415e-9f4f-c4fb01098e57` | meetup+97@bsidesottawa.ca | range_instance=134 |
| `4c9c505a-cfb2-4437-88fe-f3342e1151c7` | meetup+99@bsidesottawa.ca | range_instance=136 |
| `d62a0b00-728e-4ae5-801d-d60b04b8ae88` | meetup+100@bsidesottawa.ca | range_instance=30 |
| `8d6fb25b-4257-4704-b94b-6c2bb1d1b37b` | meetup+101@bsidesottawa.ca | range_instance=31 |
| `1cbcbde7-0509-417e-bb97-1f4bc0565020` | meetup+102@bsidesottawa.ca | range_instance=32 |
| `dfd2c5c3-e0cc-4d46-8344-07f83418b0b4` | meetup+103@bsidesottawa.ca | range_instance=33 |
| `4bd6fb4b-80d9-4bb0-8b04-e4859d923773` | meetup+104@bsidesottawa.ca | range_instance=34 |
| `78561427-b1fa-4c75-820a-aa9839557ed7` | meetup+105@bsidesottawa.ca | range_instance=35 |
| `2dabf4d4-fbaa-4e98-a735-a412524db38f` | meetup+108@bsidesottawa.ca | range_instance=38 |
| `664f681c-701b-44fa-bb79-654886d9d66c` | meetup+109@bsidesottawa.ca | range_instance=39 |
| `3be5d03d-57ad-46cd-a870-1dac45608056` | meetup+110@bsidesottawa.ca | range_instance=41 |
| `f197c41f-9f62-455c-b43d-9ddbeea6d73d` | claude-test+qa@bsidesottawa.ca | range_instance=138 |

## How to execute

Use the `cleanup_non_keepers.py` helper in this same directory. It reads the
same HARD-CODED keep-list (12 operator emails) and loops over all participants
in the event. Any participant whose email is not on the list gets their range
destroyed. Any operational surprise (participant count != expected, keep-list
member missing from DB, etc.) aborts before making changes.

**Default behavior is dry-run.** The script does NOT destroy anything unless
you pass `--execute` AND interactively confirm by typing the event UUID.

```
# Dry run — lists what WOULD be destroyed, no side effects
python3 scripts/polaris-aws-range/cleanup_non_keepers.py

# Execute — requires explicit --execute and a typed confirmation
python3 scripts/polaris-aws-range/cleanup_non_keepers.py --execute
```

## Safety invariants enforced by the script

1. The hard-coded keep-list is ALSO defined in this doc — cross-check before running.
2. The script aborts if any keep-list email is missing from the DB (mismatched deploy).
3. The script aborts if the total destroy count is unexpectedly high (>110 sanity).
4. Dry-run mode prints the full destroy list for review.
5. Execute mode requires you to type the event UUID to confirm.
6. The destroy loop uses `ctf.services.range.destroy_participant_range(participant_id)`
   which is the same path the portal admin UI uses — not a direct EC2 terminate.
