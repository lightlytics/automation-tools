import { complianceStandards } from './complianceStandards.js';
import { llResources } from './llResources.js';

document.addEventListener("DOMContentLoaded", function () {
    const apiForm = document.getElementById("apiForm");
    const apiEndpointSelect = document.getElementById("apiEndpoint");
    const parameterFields = document.getElementById("parameterFields");
    const submitButton = document.getElementById("submitButton");
    const loadingOverlay = document.getElementById("loadingOverlay");

    // Default shared parameters
    const defaultParameters = [
        { name: "environment_sub_domain", type: "text", placeholder: "Enter Sub Domain", required: true },
        { name: "environment_user_name", type: "text", placeholder: "Enter User Name", required: true },
        { name: "environment_password", type: "password", placeholder: "Enter Password", required: true },
        { name: "environment_f2a_token", type: "password", placeholder: "Leave blank if F2A not set" },
        { name: "ws_name", type: "text", placeholder: "Enter WS Name", required: true }
    ];

    // Unique parameters for each endpoint
    const apiParameters = {
        "/generate_cost_report_main_pipeline": [
            ...defaultParameters,
            { name: "start_timestamp", type: "date", required: true },
            { name: "end_timestamp", type: "date", required: true },
            { name: "period", type: "text", placeholder: "day/month/year", required: true }
        ],
        "/generate_cost_recommendations": [
            ...defaultParameters
        ],
        "/generate_compliance_report": [
            ...defaultParameters,
            {
                name: "compliance_standard",
                type: "select",
                options: complianceStandards,
                placeholder: "Choose Compliance Standard",
                required: true
            },
            { name: "accounts", type: "text", placeholder: "Not mandatory, filter by account separated by comma, e.g: '123123123123,321321321321'" },
            { name: "label", type: "text", placeholder: "Not mandatory, Add a specific label" }
        ],
        "/generate_export_inventory": [
            ...defaultParameters,
            {
                name: "resource_type",
                type: "select",
                options: llResources.map(({ value, displayName }) => ({ value, label: displayName })),
                placeholder: "Choose Resource Type",
                required: true
            },
            { name: "accounts", type: "text", placeholder: "Not mandatory, filter by account separated by comma, e.g: '123123123123,321321321321'" },
            { name: "tags", type: "text", placeholder: "Not mandatory, Tags to filter by, example: 'key=Name|value~=test,key=Vendor|value=Lightlytics'" }
        ]
    };

    // Function to populate parameter labels and input fields
    function populateParameterLabels(selectedParameters) {
        parameterFields.innerHTML = ""; // Clear existing parameter fields
        document.getElementById("responseOutput").classList.add("d-none");

        selectedParameters.forEach(parameter => {
            const inputGroup = document.createElement("div");
            inputGroup.classList.add("mb-3");

            if (parameter.type === "select") {
                const selectElement = document.createElement("select");
                selectElement.classList.add("form-select");
                selectElement.id = parameter.name;
                selectElement.name = parameter.name;
                selectElement.required = parameter.required || false;

                const defaultOption = document.createElement("option");
                defaultOption.value = "";
                defaultOption.textContent = parameter.placeholder;
                selectElement.appendChild(defaultOption);

                parameter.options.forEach(option => {
                    const optionElement = document.createElement("option");
                    optionElement.value = option.value || option; // Check if option is an object with value property
                    optionElement.textContent = option.label || option; // Check if option is an object with label property
                    selectElement.appendChild(optionElement);
                });

                const displayName = parameterDisplayNames[parameter.name] || parameter.displayName || parameter.name;
                inputGroup.innerHTML = `
                    <label for="${parameter.name}" class="form-label">${displayName}</label>
                `;
                inputGroup.appendChild(selectElement);
            } else {
                const displayName = parameterDisplayNames[parameter.name] || parameter.name;
                inputGroup.innerHTML = `
                    <label for="${parameter.name}" class="form-label">${displayName}</label>
                    <input type="${parameter.type}" class="form-control" id="${parameter.name}" name="${parameter.name}" placeholder="${parameter.placeholder}" ${parameter.required ? "required" : ""}>
                `;
            }

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
        populateParameterLabels(selectedParameters);
    });
    // Add event listener for form submission
    apiForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        document.getElementById("responseOutput").classList.add("d-none")

        submitButton.disabled = true;
        loadingOverlay.classList.remove("d-none");

        const endpoint = apiEndpointSelect.value;
        const requestData = constructPayload();

        // Load and play the Lottie animation
        playLottieAnimation();

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
                try {
                    const responseData = await response.json();
                    document.getElementById("responseOutput").classList.remove("d-none")
                    if (responseData.detail) {
                        document.getElementById("responseOutput").textContent = responseData.detail;
                    } else {
                        document.getElementById("responseOutput").textContent = JSON.stringify(responseData, null, 2);
                    }
                } catch (error) {
                    console.error("Error parsing JSON response:", error);
                    document.getElementById("responseOutput").textContent = "An error occurred while processing the response.";
                }
            } else {
                const responseBlob = await response.blob();
                const link = document.createElement("a");
                link.href = window.URL.createObjectURL(responseBlob);
                link.download = fileName;
                link.click();
            }
        } finally {
            if (animation) {
                animation.destroy(); // Stop the animation
                animation = null; // Reset animation variable
            }
            loadingOverlay.classList.add("d-none");
            submitButton.disabled = false;
        }
    });

    // Trigger the API endpoint change event to load initial parameters
    apiEndpointSelect.dispatchEvent(new Event("change"));
});

// Define the animation variable outside the event handler
let animation = null;

// Load and play the Lottie animation
async function playLottieAnimation() {
    if (animation) {
        return animation; // Animation is already playing, return it
    }

    try {
        const response = await fetch("/static/spinner.json");
        const animationConfig = await response.json();

        const lottieContainer = document.getElementById("lottieContainer");
        animation = lottie.loadAnimation({
            container: lottieContainer,
            renderer: "svg",
            loop: true,
            autoplay: true,
            animationData: animationConfig
        });

        return animation;
    } catch (error) {
        console.error("Error loading animation configuration:", error);
        return null;
    }
}

const parameterDisplayNames = {
    "environment_sub_domain": "Environment Sub-Domain (<strong>xyz</strong>.streamsec.io)",
    "environment_user_name": "Environment User Name (Email)",
    "environment_password": "Environment Password",
    "environment_f2a_token": "Environment F2A Token",
    "ws_name": "Workspace Name",
    "start_timestamp": "Start Date",
    "end_timestamp": "End Date",
    "period": "Period (day/month/year)",
    "accounts": "Selected Accounts",
    "tags": "Selected Tags",
    "compliance_standard": "Compliance Standard to use",
    "label": "Label to use",
    "resource_type": "Resource Type"
};
