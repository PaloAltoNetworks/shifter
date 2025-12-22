#!/bin/bash
# Dev box management script
# Usage: ./scripts/dev-box.sh [command]
#   start   - Start the dev box (if stopped)
#   stop    - Stop the dev box (save costs)
#   status  - Check current status
#   connect - Open Fleet Manager RDP in browser
#   ssh     - Start SSM session (CLI access)

set -e

AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:-panw-shifter-dev}"
REGION="us-east-2"
INSTANCE_NAME="shifter-dev-box"

# Get instance ID by name tag
get_instance_id() {
    aws ec2 describe-instances \
        --profile "$AWS_PROFILE" \
        --region "$REGION" \
        --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
        --query 'Reservations[0].Instances[0].InstanceId' \
        --output text 2>/dev/null
}

# Get instance state
get_instance_state() {
    local instance_id="$1"
    aws ec2 describe-instances \
        --profile "$AWS_PROFILE" \
        --region "$REGION" \
        --instance-ids "$instance_id" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text 2>/dev/null
}

# Get public IP
get_public_ip() {
    local instance_id="$1"
    aws ec2 describe-instances \
        --profile "$AWS_PROFILE" \
        --region "$REGION" \
        --instance-ids "$instance_id" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text 2>/dev/null
}

case "${1:-status}" in
    start)
        instance_id=$(get_instance_id)
        if [ "$instance_id" = "None" ] || [ -z "$instance_id" ]; then
            echo "Dev box not found. Deploy it first with:"
            echo "  cd terraform/global/dev-box && terraform apply"
            exit 1
        fi

        state=$(get_instance_state "$instance_id")
        if [ "$state" = "running" ]; then
            echo "Dev box is already running"
        else
            echo "Starting dev box..."
            aws ec2 start-instances \
                --profile "$AWS_PROFILE" \
                --region "$REGION" \
                --instance-ids "$instance_id" > /dev/null
            echo "Waiting for instance to start..."
            aws ec2 wait instance-running \
                --profile "$AWS_PROFILE" \
                --region "$REGION" \
                --instance-ids "$instance_id"
            echo "Dev box started!"
        fi

        echo ""
        echo "Connect with: ./scripts/dev-box.sh connect"
        ;;

    stop)
        instance_id=$(get_instance_id)
        if [ "$instance_id" = "None" ] || [ -z "$instance_id" ]; then
            echo "Dev box not found"
            exit 1
        fi

        echo "Stopping dev box..."
        aws ec2 stop-instances \
            --profile "$AWS_PROFILE" \
            --region "$REGION" \
            --instance-ids "$instance_id" > /dev/null
        echo "Dev box stopping (saves costs when not in use)"
        ;;

    status)
        instance_id=$(get_instance_id)
        if [ "$instance_id" = "None" ] || [ -z "$instance_id" ]; then
            echo "Dev box not found. Deploy it first with:"
            echo "  cd terraform/global/dev-box && terraform apply"
            exit 1
        fi

        state=$(get_instance_state "$instance_id")
        public_ip=$(get_public_ip "$instance_id")

        echo "Dev Box Status"
        echo "=============="
        echo "Instance ID: $instance_id"
        echo "State:       $state"
        [ "$public_ip" != "None" ] && echo "Public IP:   $public_ip"
        echo ""

        if [ "$state" = "running" ]; then
            echo "Commands:"
            echo "  ./scripts/dev-box.sh connect  - Open Fleet Manager RDP"
            echo "  ./scripts/dev-box.sh ssh      - CLI session"
            echo "  ./scripts/dev-box.sh stop     - Stop to save costs"
        else
            echo "Run './scripts/dev-box.sh start' to start the instance"
        fi
        ;;

    connect)
        instance_id=$(get_instance_id)
        if [ "$instance_id" = "None" ] || [ -z "$instance_id" ]; then
            echo "Dev box not found"
            exit 1
        fi

        state=$(get_instance_state "$instance_id")
        if [ "$state" != "running" ]; then
            echo "Dev box is not running. Start it first:"
            echo "  ./scripts/dev-box.sh start"
            exit 1
        fi

        url="https://${REGION}.console.aws.amazon.com/systems-manager/fleet-manager/${instance_id}/connect?region=${REGION}"
        echo "Opening Fleet Manager RDP..."
        echo "URL: $url"
        echo ""
        echo "Note: Select 'Connect with Remote Desktop' in Fleet Manager"

        # Try to open browser
        if command -v xdg-open &> /dev/null; then
            xdg-open "$url" 2>/dev/null || echo "Open the URL above in your browser"
        elif command -v open &> /dev/null; then
            open "$url"
        else
            echo "Open the URL above in your browser"
        fi
        ;;

    ssh)
        instance_id=$(get_instance_id)
        if [ "$instance_id" = "None" ] || [ -z "$instance_id" ]; then
            echo "Dev box not found"
            exit 1
        fi

        state=$(get_instance_state "$instance_id")
        if [ "$state" != "running" ]; then
            echo "Dev box is not running. Start it first:"
            echo "  ./scripts/dev-box.sh start"
            exit 1
        fi

        echo "Starting SSM session to $instance_id..."
        aws ssm start-session \
            --profile "$AWS_PROFILE" \
            --region "$REGION" \
            --target "$instance_id"
        ;;

    tunnel)
        instance_id=$(get_instance_id)
        if [ "$instance_id" = "None" ] || [ -z "$instance_id" ]; then
            echo "Dev box not found"
            exit 1
        fi

        state=$(get_instance_state "$instance_id")
        if [ "$state" != "running" ]; then
            echo "Dev box is not running. Start it first:"
            echo "  ./scripts/dev-box.sh start"
            exit 1
        fi

        local_port="${2:-33389}"
        echo "Starting RDP tunnel to $instance_id..."
        echo "Connect your RDP client to: localhost:$local_port"
        echo ""
        echo "Press Ctrl+C to close the tunnel"
        echo ""
        aws ssm start-session \
            --profile "$AWS_PROFILE" \
            --region "$REGION" \
            --target "$instance_id" \
            --document-name AWS-StartPortForwardingSession \
            --parameters "{\"portNumber\":[\"3389\"],\"localPortNumber\":[\"$local_port\"]}"
        ;;

    *)
        echo "Usage: $0 {start|stop|status|connect|ssh|tunnel}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the dev box"
        echo "  stop    - Stop the dev box (saves costs)"
        echo "  status  - Show current status"
        echo "  connect - Open Fleet Manager RDP in browser"
        echo "  ssh     - Start SSM CLI session"
        echo "  tunnel  - Start RDP tunnel (default: localhost:33389)"
        exit 1
        ;;
esac
