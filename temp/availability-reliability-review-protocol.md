# Availability & Reliability Review Protocol

**Target Role:** Principal DevOps Engineer
**Review Type:** Production System Health Assessment
**Focus Areas:** Availability (uptime) & Reliability (correctness)

## Review Execution Guidelines

- Each item should be verified with evidence (logs, metrics, screenshots, query results)
- Document findings in a separate report with timestamps
- Categorize issues by severity: Critical (P0), High (P1), Medium (P2), Low (P3)
- Track action items with owners and due dates
- Review should be conducted quarterly or after major incidents

---

## 1. Infrastructure Availability

### 1.1 Compute Resources

- [ ] Verify all critical EC2 instances are running and healthy
  - [ ] Check instance status checks (system and instance)
  - [ ] Verify instance metrics: CPU, memory, disk, network
  - [ ] Confirm instances are in correct availability zones
  - [ ] Validate instance types match requirements
  - [ ] Check for any retired/deprecated instance types

- [ ] Review Auto Scaling Group configuration
  - [ ] Verify desired capacity matches actual running instances
  - [ ] Check min/max capacity settings are appropriate
  - [ ] Validate scaling policies and thresholds
  - [ ] Review scaling history for unexpected scaling events
  - [ ] Confirm health check grace periods are adequate
  - [ ] Verify cooldown periods prevent thrashing

- [ ] Validate ECS/Container infrastructure (if applicable)
  - [ ] Check ECS cluster capacity and task distribution
  - [ ] Verify service desired count matches running tasks
  - [ ] Review task definition versions and rollback capability
  - [ ] Confirm container health checks are configured
  - [ ] Validate task placement strategies
  - [ ] Check for stopped/failed tasks and investigate causes

### 1.2 Network Infrastructure

- [ ] Load balancer health and configuration
  - [ ] Verify all target groups have healthy targets
  - [ ] Check load balancer metrics: request count, latency, error rates
  - [ ] Review connection draining/deregistration delay settings
  - [ ] Validate stickiness configuration if enabled
  - [ ] Confirm SSL/TLS certificates are valid (>30 days until expiry)
  - [ ] Check load balancer logs for anomalies

- [ ] VPC and network connectivity
  - [ ] Verify route table configurations
  - [ ] Check security group rules for overly permissive access
  - [ ] Validate NACL rules aren't blocking legitimate traffic
  - [ ] Confirm VPC peering connections are active
  - [ ] Review VPC flow logs for denied connections
  - [ ] Validate NAT gateway/instance availability and capacity

- [ ] DNS resolution
  - [ ] Verify Route53 health checks are passing
  - [ ] Check DNS record TTLs are appropriate
  - [ ] Validate DNSSEC if configured
  - [ ] Review DNS query logs for anomalies
  - [ ] Confirm failover routing policies work correctly

### 1.3 Data Persistence

- [ ] Database availability
  - [ ] Check RDS/database instance status and metrics
  - [ ] Verify multi-AZ configuration is active
  - [ ] Review database connection pool metrics
  - [ ] Check for replication lag (if using read replicas)
  - [ ] Validate automated backup schedule and retention
  - [ ] Confirm point-in-time recovery is enabled
  - [ ] Review database error logs for issues
  - [ ] Check storage capacity and I/O credit balance

- [ ] Object storage
  - [ ] Verify S3 bucket versioning configuration
  - [ ] Check bucket replication status (if configured)
  - [ ] Review S3 metrics: request counts, error rates
  - [ ] Validate lifecycle policies
  - [ ] Confirm critical buckets have deletion protection

- [ ] Cache availability
  - [ ] Check ElastiCache/Redis cluster status
  - [ ] Verify cache hit/miss ratios
  - [ ] Review eviction metrics
  - [ ] Confirm cluster mode and replication configuration
  - [ ] Check for memory pressure or swap usage

---

## 2. Application Availability

### 2.1 Service Health

- [ ] Application process health
  - [ ] Verify all application processes are running
  - [ ] Check process restart frequency and causes
  - [ ] Review application logs for startup errors
  - [ ] Validate worker/background job processors are running
  - [ ] Confirm scheduled tasks/cron jobs are executing

- [ ] Health endpoints
  - [ ] Verify /health or equivalent endpoint responds correctly
  - [ ] Check health endpoint response time
  - [ ] Validate health checks test critical dependencies
  - [ ] Review health check failure history
  - [ ] Confirm health checks don't cause performance impact

- [ ] Application metrics
  - [ ] Review request rate and throughput trends
  - [ ] Check error rate percentage
  - [ ] Analyze response time percentiles (p50, p95, p99)
  - [ ] Verify active connection counts are normal
  - [ ] Review thread pool/worker utilization

### 2.2 Dependency Health

- [ ] External API availability
  - [ ] Check integration status with third-party services
  - [ ] Review API response times and error rates
  - [ ] Verify circuit breakers are configured and functioning
  - [ ] Validate timeout configurations are appropriate
  - [ ] Confirm retry logic and backoff strategies work
  - [ ] Review rate limiting behavior

- [ ] Internal service dependencies
  - [ ] Verify microservice mesh connectivity
  - [ ] Check service-to-service authentication
  - [ ] Review service discovery health
  - [ ] Validate API gateway functionality
  - [ ] Confirm service mesh metrics (if using Istio/Linkerd)

### 2.3 Async Processing

- [ ] Message queue health
  - [ ] Check SQS/message broker queue depths
  - [ ] Verify DLQ (dead letter queue) messages are reviewed
  - [ ] Review message processing latency
  - [ ] Confirm message retention policies
  - [ ] Validate queue visibility timeout settings
  - [ ] Check for message poison patterns

- [ ] Background job processing
  - [ ] Verify Celery/worker task completion rates
  - [ ] Check for stuck or long-running tasks
  - [ ] Review task failure rates and error types
  - [ ] Validate worker pool sizing
  - [ ] Confirm task retry configuration
  - [ ] Check task result backend performance

---

## 3. Monitoring & Observability

### 3.1 Metrics Collection

- [ ] Metrics pipeline health
  - [ ] Verify CloudWatch/metrics agent is running on all hosts
  - [ ] Check for gaps in metric data
  - [ ] Validate custom metrics are being collected
  - [ ] Review metric retention policies
  - [ ] Confirm metric cardinality isn't excessive
  - [ ] Check for metric submission errors

- [ ] Key metrics validation
  - [ ] Verify availability/uptime metrics are accurate
  - [ ] Check SLI (Service Level Indicator) calculations
  - [ ] Review error budget consumption
  - [ ] Validate latency percentile calculations
  - [ ] Confirm throughput metrics match reality

### 3.2 Logging Infrastructure

- [ ] Log collection and aggregation
  - [ ] Verify log shipping agents are running
  - [ ] Check for log delivery lag or backlogs
  - [ ] Review log volume trends
  - [ ] Validate log retention meets compliance requirements
  - [ ] Confirm log encryption in transit and at rest
  - [ ] Check log storage capacity

- [ ] Log quality and completeness
  - [ ] Verify error logs are being captured
  - [ ] Check for missing correlation IDs/request IDs
  - [ ] Review log levels across services
  - [ ] Validate structured logging format
  - [ ] Confirm PII is properly redacted
  - [ ] Check that debug logs aren't enabled in production

### 3.3 Alerting Configuration

- [ ] Alert coverage
  - [ ] Verify alerts exist for all critical failure modes
  - [ ] Check for alert coverage gaps
  - [ ] Review alert thresholds for appropriateness
  - [ ] Validate alerts fire during testing
  - [ ] Confirm composite/multi-condition alerts work
  - [ ] Check for alert dependencies and suppression rules

- [ ] Alert quality
  - [ ] Review alert firing frequency (avoid fatigue)
  - [ ] Check mean time to acknowledge (MTTA)
  - [ ] Analyze false positive rate
  - [ ] Verify alert descriptions are actionable
  - [ ] Confirm runbook links are present and accurate
  - [ ] Validate alert routing and escalation paths

- [ ] Alert delivery
  - [ ] Verify notification channels are working
  - [ ] Check for alert delivery failures
  - [ ] Review on-call schedule coverage
  - [ ] Validate alert deduplication logic
  - [ ] Confirm critical alerts bypass quiet hours
  - [ ] Test alert delivery to all channels

---

## 4. Reliability & Correctness

### 4.1 Data Integrity

- [ ] Database consistency
  - [ ] Run database integrity checks (DBCC, pg_check, etc.)
  - [ ] Verify foreign key constraints are enforced
  - [ ] Check for orphaned records
  - [ ] Review database transaction isolation levels
  - [ ] Validate data replication consistency
  - [ ] Confirm backup restoration works (test restore)

- [ ] Data validation
  - [ ] Review application-level data validation
  - [ ] Check for data corruption in logs
  - [ ] Verify ETL/data pipeline correctness
  - [ ] Validate data transformation logic
  - [ ] Confirm idempotency of operations
  - [ ] Check for duplicate data issues

- [ ] State management
  - [ ] Verify distributed lock mechanisms work correctly
  - [ ] Check session state consistency
  - [ ] Review cache invalidation patterns
  - [ ] Validate event sourcing integrity (if applicable)
  - [ ] Confirm state machine transitions are correct

### 4.2 Business Logic Correctness

- [ ] Functional testing coverage
  - [ ] Review smoke test results in production
  - [ ] Verify synthetic transaction monitoring
  - [ ] Check A/B test configuration and results
  - [ ] Validate feature flag states
  - [ ] Confirm critical user flows are monitored
  - [ ] Review canary deployment behavior

- [ ] Data consistency checks
  - [ ] Verify financial calculations are accurate
  - [ ] Check inventory/stock counts match reality
  - [ ] Review user account states for inconsistencies
  - [ ] Validate audit trail completeness
  - [ ] Confirm rate limiting is working correctly
  - [ ] Check access control enforcement

### 4.3 Configuration Management

- [ ] Configuration validation
  - [ ] Verify production configuration matches expected state
  - [ ] Check for configuration drift
  - [ ] Review environment variable consistency
  - [ ] Validate feature flags are set correctly
  - [ ] Confirm secrets rotation is working
  - [ ] Check for hardcoded credentials (none should exist)

- [ ] Infrastructure as Code
  - [ ] Verify Terraform/IaC state matches reality
  - [ ] Check for manual changes outside IaC
  - [ ] Review IaC drift detection results
  - [ ] Validate IaC module versions
  - [ ] Confirm IaC backend state is backed up
  - [ ] Check for unused/orphaned resources

---

## 5. Disaster Recovery & Resilience

### 5.1 Backup Verification

- [ ] Backup completeness
  - [ ] Verify all critical data is being backed up
  - [ ] Check backup success/failure rates
  - [ ] Review backup size trends for anomalies
  - [ ] Validate backup schedules meet RPO requirements
  - [ ] Confirm backup retention meets requirements
  - [ ] Check for backup storage capacity issues

- [ ] Restore capability
  - [ ] Test database restore (do actual restore to staging)
  - [ ] Verify restore documentation is current
  - [ ] Check restore time meets RTO requirements
  - [ ] Validate point-in-time recovery works
  - [ ] Confirm cross-region backup copies exist
  - [ ] Test application data restore procedures

### 5.2 Failure Mode Analysis

- [ ] Single points of failure
  - [ ] Identify and document SPOFs
  - [ ] Verify redundancy for critical components
  - [ ] Check for shared dependencies
  - [ ] Review single-AZ resources
  - [ ] Validate cross-region failover capability
  - [ ] Confirm database failover procedures work

- [ ] Chaos engineering validation
  - [ ] Review recent chaos experiment results
  - [ ] Verify system behavior under load
  - [ ] Test graceful degradation
  - [ ] Validate circuit breaker behavior
  - [ ] Confirm bulkhead isolation works
  - [ ] Test rate limiting under stress

### 5.3 Incident Response Readiness

- [ ] Documentation currency
  - [ ] Verify runbooks are up to date
  - [ ] Check incident response procedures
  - [ ] Review contact lists and escalation paths
  - [ ] Validate architecture diagrams are current
  - [ ] Confirm rollback procedures are documented
  - [ ] Check disaster recovery plan date

- [ ] Team preparedness
  - [ ] Review recent incident response performance
  - [ ] Verify on-call rotation is staffed
  - [ ] Check that team has production access
  - [ ] Validate incident communication channels
  - [ ] Confirm post-mortem follow-up items are resolved
  - [ ] Review incident response training dates

---

## 6. Capacity & Performance

### 6.1 Resource Utilization

- [ ] Compute capacity
  - [ ] Review CPU utilization trends (aim for 50-70% avg)
  - [ ] Check memory utilization and swap usage
  - [ ] Verify disk I/O capacity
  - [ ] Review network bandwidth utilization
  - [ ] Validate headroom for traffic spikes
  - [ ] Check for resource contention

- [ ] Database capacity
  - [ ] Review database connection pool utilization
  - [ ] Check query performance and slow query logs
  - [ ] Verify index usage and effectiveness
  - [ ] Review database storage growth rate
  - [ ] Validate read/write IOPS capacity
  - [ ] Check for table/index bloat

- [ ] Storage capacity
  - [ ] Review disk space trends (alert at 70-80%)
  - [ ] Check log file retention and rotation
  - [ ] Verify S3 storage growth rates
  - [ ] Validate storage lifecycle policies
  - [ ] Confirm no partitions are full
  - [ ] Check for large file accumulation

### 6.2 Performance Baselines

- [ ] Latency analysis
  - [ ] Compare current p95/p99 latency to baseline
  - [ ] Review API endpoint performance
  - [ ] Check database query latency trends
  - [ ] Verify cache performance metrics
  - [ ] Validate CDN cache hit rates
  - [ ] Review inter-service communication latency

- [ ] Throughput analysis
  - [ ] Compare current RPS to baseline
  - [ ] Review transaction processing rates
  - [ ] Check batch job completion times
  - [ ] Verify concurrent user capacity
  - [ ] Validate async job processing rates
  - [ ] Review data pipeline throughput

### 6.3 Scaling Capability

- [ ] Horizontal scaling
  - [ ] Verify autoscaling triggers are appropriate
  - [ ] Check scale-out and scale-in behavior
  - [ ] Review scaling velocity (time to add capacity)
  - [ ] Validate maximum capacity limits
  - [ ] Confirm load distribution after scaling
  - [ ] Test scaling during high load

- [ ] Vertical scaling
  - [ ] Review instance/container size appropriateness
  - [ ] Check for memory-bound workloads
  - [ ] Verify CPU-bound workload optimization
  - [ ] Validate storage performance tiers
  - [ ] Confirm database instance class suitability
  - [ ] Review cost vs. performance tradeoffs

---

## 7. Security & Compliance

### 7.1 Security Posture

- [ ] Access controls
  - [ ] Review IAM policies and permissions
  - [ ] Verify principle of least privilege
  - [ ] Check for overly permissive roles
  - [ ] Validate MFA enforcement
  - [ ] Review security group rules
  - [ ] Confirm network ACLs are restrictive

- [ ] Vulnerability management
  - [ ] Check for unpatched systems
  - [ ] Review security scanning results
  - [ ] Verify CVE remediation status
  - [ ] Validate dependency scanning results
  - [ ] Confirm container image scanning
  - [ ] Check for exposed secrets

- [ ] Encryption validation
  - [ ] Verify data at rest encryption
  - [ ] Check data in transit encryption (TLS 1.2+)
  - [ ] Review key rotation schedules
  - [ ] Validate encryption key access controls
  - [ ] Confirm database encryption is enabled
  - [ ] Check S3 bucket encryption settings

### 7.2 Compliance Requirements

- [ ] Audit logging
  - [ ] Verify CloudTrail is enabled and logging
  - [ ] Check for audit log tampering protections
  - [ ] Review audit log retention periods
  - [ ] Validate audit log integrity
  - [ ] Confirm compliance with regulatory requirements
  - [ ] Check for audit log completeness

- [ ] Data governance
  - [ ] Verify data retention policies are enforced
  - [ ] Check for PII/PHI handling compliance
  - [ ] Review data classification implementation
  - [ ] Validate data residency requirements
  - [ ] Confirm right-to-delete capabilities
  - [ ] Check data export/portability features

---

## 8. Operational Excellence

### 8.1 Deployment Pipeline

- [ ] CI/CD health
  - [ ] Verify build pipeline success rates
  - [ ] Check deployment frequency and lead time
  - [ ] Review rollback frequency and causes
  - [ ] Validate automated testing coverage
  - [ ] Confirm deployment approval gates work
  - [ ] Check for failed deployments

- [ ] Release management
  - [ ] Review change failure rate
  - [ ] Verify deployment strategies (blue/green, canary)
  - [ ] Check feature flag usage and cleanup
  - [ ] Validate release notes and changelog
  - [ ] Confirm deployment windows are followed
  - [ ] Review deployment communication process

### 8.2 Cost Optimization

- [ ] Resource efficiency
  - [ ] Identify idle or underutilized resources
  - [ ] Review Reserved Instance/Savings Plan coverage
  - [ ] Check for zombie resources
  - [ ] Validate right-sizing recommendations
  - [ ] Review data transfer costs
  - [ ] Confirm cost anomaly detection alerts

- [ ] Cost allocation
  - [ ] Verify resource tagging for cost tracking
  - [ ] Review cost trends by service/team
  - [ ] Check for unexpected cost increases
  - [ ] Validate budget alerts are configured
  - [ ] Confirm cost optimization opportunities
  - [ ] Review FinOps recommendations

### 8.3 Documentation & Knowledge

- [ ] Documentation completeness
  - [ ] Verify architecture diagrams are current
  - [ ] Check that runbooks are accessible
  - [ ] Review operational procedures documentation
  - [ ] Validate API documentation currency
  - [ ] Confirm troubleshooting guides exist
  - [ ] Check for stale documentation

- [ ] Knowledge sharing
  - [ ] Review post-mortem action items closure
  - [ ] Verify incident lessons learned are documented
  - [ ] Check that knowledge base is maintained
  - [ ] Validate team onboarding documentation
  - [ ] Confirm tribal knowledge is captured
  - [ ] Review architectural decision records (ADRs)

---

## 9. Third-Party Dependencies

### 9.1 External Service Health

- [ ] SaaS provider status
  - [ ] Check status pages of critical vendors
  - [ ] Review SLA compliance reports
  - [ ] Verify incident notifications are received
  - [ ] Validate vendor uptime metrics
  - [ ] Confirm escalation contacts are current
  - [ ] Review vendor security posture

- [ ] API integrations
  - [ ] Verify third-party API health
  - [ ] Check for deprecation notices
  - [ ] Review API version currency
  - [ ] Validate rate limiting compliance
  - [ ] Confirm webhook delivery reliability
  - [ ] Check API authentication token expiry

### 9.2 Software Dependencies

- [ ] Package management
  - [ ] Review outdated package dependencies
  - [ ] Check for deprecated libraries
  - [ ] Verify security vulnerability scanning
  - [ ] Validate dependency license compliance
  - [ ] Confirm supply chain security measures
  - [ ] Check for abandoned dependencies

- [ ] Runtime dependencies
  - [ ] Verify language runtime versions
  - [ ] Check for EOL (end-of-life) runtimes
  - [ ] Review framework version currency
  - [ ] Validate database driver compatibility
  - [ ] Confirm OS/kernel version support status
  - [ ] Check container base image updates

---

## 10. Review Summary & Actions

### 10.1 Findings Documentation

- [ ] Categorize findings by severity
- [ ] Document evidence for each finding
- [ ] Estimate impact of each issue
- [ ] Calculate risk scores
- [ ] Prioritize remediation actions
- [ ] Assign owners to action items

### 10.2 Metrics Summary

- [ ] Calculate current availability percentage
- [ ] Measure against SLO/SLA targets
- [ ] Document error budget status
- [ ] Summarize key performance indicators
- [ ] Track improvement trends
- [ ] Compare to previous review results

### 10.3 Action Planning

- [ ] Create remediation roadmap
- [ ] Set deadlines for critical items
- [ ] Schedule follow-up reviews
- [ ] Communicate findings to stakeholders
- [ ] Track action item completion
- [ ] Update system documentation

---

## Appendix: Useful Commands & Queries

### AWS CLI Commands
```bash
# Check EC2 instance status
aws ec2 describe-instance-status --instance-ids <id>

# Check RDS database status
aws rds describe-db-instances --db-instance-identifier <id>

# Review load balancer targets
aws elbv2 describe-target-health --target-group-arn <arn>

# Check Auto Scaling group health
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names <name>

# Review CloudWatch alarms
aws cloudwatch describe-alarms --state-value ALARM
```

### Database Queries
```sql
-- PostgreSQL: Check database size and growth
SELECT pg_size_pretty(pg_database_size(current_database()));

-- Check long-running queries
SELECT pid, now() - query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active' AND query_start < now() - interval '5 minutes';

-- Check replication lag
SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) AS lag_seconds;
```

### System Commands
```bash
# Check disk usage
df -h

# Check memory usage
free -h

# Check process status
systemctl status <service>

# Check recent errors in logs
journalctl -u <service> -p err -n 100

# Check network connections
netstat -tunap | grep <port>
```

---

**Review Frequency:** Quarterly or post-incident
**Estimated Duration:** 4-8 hours (depending on system complexity)
**Required Access:** AWS Console, SSH/SSM access, database access, monitoring dashboards
**Artifacts:** Review report, action items list, risk register update
