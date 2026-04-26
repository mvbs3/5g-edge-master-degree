start-5g-core:
	docker compose -f sa-deploy.yaml up -d
	sleep 5


start-5g-core-debug:
	docker compose -f sa-deploy.yaml up
	sleep 5

enable-forward:
	sudo sysctl -w net.ipv4.conf.all.forwarding=1
	sudo iptables -P FORWARD ACCEPT

stop-5g-core:
	docker compose -f sa-deploy.yaml down
