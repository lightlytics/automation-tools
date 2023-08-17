document.addEventListener("DOMContentLoaded", function () {
    const apiForm = document.getElementById("apiForm");
    const apiEndpointSelect = document.getElementById("apiEndpoint");
    const parameterFields = document.getElementById("parameterFields");
    const submitButton = document.getElementById("submitButton");
    const loadingOverlay = document.getElementById("loadingOverlay");

    // Default shared parameters
    const defaultParameters = [
        { name: "environment_sub_domain", type: "text", placeholder: "Enter Sub Domain" },
        { name: "environment_user_name", type: "text", placeholder: "Enter User Name" },
        { name: "environment_password", type: "password", placeholder: "Enter Password" },
        { name: "ws_name", type: "text", placeholder: "Enter WS Name" }
    ];

    // Unique parameters for each endpoint
    const apiParameters = {
        "/generate_cost_report": [
            ...defaultParameters,
            { name: "start_timestamp", type: "date" },
            { name: "end_timestamp", type: "date" },
            { name: "period", type: "text", placeholder: "day/month/year" },
            { name: "stage", type: "text", placeholder: "Leave Blank" }
        ],
        "/generate_cost_recommendations": [
            ...defaultParameters,
            { name: "stage", type: "text", placeholder: "Leave Blank" }
        ],
        "/generate_compliance_report": [
            ...defaultParameters,
            { name: "compliance_standard", type: "text", placeholder: "Choose Compliance Standard" },
            { name: "accounts", type: "text", placeholder: "Not mandatory, filter by account separated by comma, e.g: '123123123123,321321321321'" },
            { name: "label", type: "text", placeholder: "Not mandatory, Add a specific label" },
            { name: "stage", type: "text", placeholder: "Leave Blank" }
        ],
        "/generate_export_inventory": [
            ...defaultParameters,
            { name: "resource_type", type: "text", placeholder: "Resource Type, e.g: 'instance', 'security_group'" },
            { name: "accounts", type: "text", placeholder: "Not mandatory, filter by account separated by comma, e.g: '123123123123,321321321321'" },
            { name: "accounts", type: "text", placeholder: "Not mandatory, Tags to filter by, example: 'key=Name|value~=test,key=Vendor|value=Lightlytics'" },
            { name: "stage", type: "text", placeholder: "Leave Blank" }
        ]
    };

    // Function to generate input boxes for the selected parameters
    function generateInputBoxes(parameters) {
        parameterFields.innerHTML = ""; // Clear existing parameter fields

        parameters.forEach(parameter => {
            const inputGroup = document.createElement("div");
            inputGroup.classList.add("mb-3");
            inputGroup.innerHTML = `
                <label for="${parameter.name}" class="form-label">${parameter.name}</label>
                <input type="${parameter.type}" class="form-control" id="${parameter.name}" name="${parameter.name}" placeholder="${parameter.placeholder}">
            `;
            parameterFields.appendChild(inputGroup);
        });
    }

    // Function to gather parameter values and construct JSON payload
    function constructPayload() {
        const selectedEndpoint = apiEndpointSelect.value;
        const selectedParameters = apiParameters[selectedEndpoint];

        const payload = {};
        selectedParameters.forEach(parameter => {
            const inputValue = document.getElementById(parameter.name).value;
            payload[parameter.name] = inputValue;
        });

        return JSON.stringify(payload);
    }

    // Add event listener for API endpoint change
    apiEndpointSelect.addEventListener("change", function () {
        const selectedParameters = apiParameters[this.value];
        generateInputBoxes(selectedParameters);
    });

    // Add event listener for form submission
    apiForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        submitButton.disabled = true;
        loadingOverlay.classList.remove("d-none");

        const endpoint = apiEndpointSelect.value;
        const requestData = constructPayload();

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: requestData
            });

            const contentType = response.headers.get("content-type");
            const contentDisposition = response.headers.get("content-disposition");
            let fileName = "response";

            if (contentDisposition) {
                fileName = contentDisposition.split("; ")[1].replace("filename=", "").replace(/\"/g, "");
                // Remove the trailing underscore if present
                fileName = fileName.replace(/_$/, "");
            }

            if (contentType.includes("application/json")) {
                const responseData = await response.text();
                document.getElementById("responseOutput").textContent = responseData;
            } else {
                const responseBlob = await response.blob();
                const link = document.createElement("a");
                link.href = window.URL.createObjectURL(responseBlob);
                link.download = fileName;
                link.click();
            }
        } finally {
            loadingOverlay.classList.add("d-none");
            submitButton.disabled = false;
        }
    });

    // Trigger the API endpoint change event to load initial parameters
    apiEndpointSelect.dispatchEvent(new Event("change"));
});
